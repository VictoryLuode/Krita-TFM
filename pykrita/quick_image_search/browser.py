"""Synchronous, standard-library-only image search over a local Chrome CDP endpoint."""
import base64
import hashlib
import http.client
import json
import os
import secrets
import socket
import struct
import shutil
import subprocess
from pathlib import Path
import time
import urllib.parse
from quick_image_search.network import request_bytes
from quick_image_search.process_owner import ProcessOwner
import urllib.request
from quick_image_search.task_runtime import (Token, task_scope, current_token, check_cancelled, interruptible_sleep)


class BrowserUnavailable(Exception):
    """The configured local Chrome CDP endpoint cannot be reached safely."""


class VerificationRequired(Exception):
    """A search provider requires a human verification or login."""


class SearchError(Exception):
    """A search request or result resolution failed."""


MAX_HTTP = 1_000_000
MAX_FRAME = 4_000_000
TIMEOUT = 20


def _result_id(source, thumbnail):
    parsed = urllib.parse.urlsplit(thumbnail)
    if source == 'pinterest' and parsed.hostname == 'i.pinimg.com':
        identity = parsed.path.rsplit('/', 1)[-1]
    elif source == 'google':
        identity = urllib.parse.parse_qs(parsed.query).get('q', [thumbnail])[0]
    else:
        identity = thumbnail
    return hashlib.sha256((source + '\0' + identity).encode()).hexdigest()[:24]


def _validate_cdp_url(url):
    p = urllib.parse.urlsplit(url or "")
    if p.scheme != "ws" or p.hostname != "127.0.0.1" or not p.port or p.username or p.password:
        raise BrowserUnavailable("CDP WebSocket must be a ws://127.0.0.1 endpoint")
    return p


class _WebSocket:
    """Minimal RFC6455 client for local, unencrypted Chrome WebSocket connections."""
    def __init__(self, sock, timeout=TIMEOUT, max_frame=MAX_FRAME):
        self.sock, self.timeout, self.max_frame = sock, timeout, max_frame
        self.sock.settimeout(min(timeout, .1))
        self._read_deadline = time.monotonic()+timeout

    @classmethod
    def connect(cls, url):
        p = _validate_cdp_url(url)
        check_cancelled()
        sock = socket.create_connection(("127.0.0.1", p.port), timeout=1)
        sock.settimeout(.1)
        deadline = time.monotonic()+TIMEOUT
        try:
            key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
            path = urllib.parse.urlunsplit(("", "", p.path or "/", p.query, ""))
            req = ("GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1\r\n\r\n" % (path, p.port, key)).encode("ascii")
            sock.sendall(req)
            response = b""
            while b"\r\n\r\n" not in response:
                check_cancelled()
                if time.monotonic() >= deadline:
                    sock.close()
                    raise TimeoutError("CDP handshake exceeded its total time limit")
                try:
                    chunk = sock.recv(1)
                except socket.timeout:
                    continue
                if not chunk or len(response) >= 16384:
                    sock.close(); raise BrowserUnavailable("Invalid CDP WebSocket handshake")
                response += chunk
            head = response.decode("latin1").split("\r\n")
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            headers = dict(line.split(":", 1) for line in head[1:] if ":" in line)
            if " 101 " not in head[0] or headers.get("Sec-WebSocket-Accept", "").strip() != expected:
                sock.close(); raise BrowserUnavailable("CDP WebSocket handshake rejected")
            return cls(sock)
        except BaseException:
            sock.close()
            raise

    def _exact(self, n):
        out = bytearray()
        while len(out) < n:
            check_cancelled()
            if time.monotonic() >= self._read_deadline:
                raise TimeoutError("CDP response exceeded its total time limit")
            try:
                part = self.sock.recv(n - len(out))
            except socket.timeout:
                continue
            if not part: raise BrowserUnavailable("CDP connection closed")
            out.extend(part)
        return bytes(out)

    def send(self, text):
        check_cancelled()
        data = text.encode("utf-8")
        if len(data) > self.max_frame: raise SearchError("CDP message exceeds size limit")
        n = len(data); head = bytearray([0x81])
        if n < 126: head.append(0x80 | n)
        elif n <= 65535: head.extend((0x80 | 126,)); head.extend(struct.pack("!H", n))
        else: head.extend((0x80 | 127,)); head.extend(struct.pack("!Q", n))
        mask = secrets.token_bytes(4)
        head.extend(mask); self.sock.sendall(head + bytes(v ^ mask[i % 4] for i, v in enumerate(data)))

    def recv(self):
        self._read_deadline = time.monotonic()+self.timeout
        chunks = bytearray()
        while True:
            a, b = self._exact(2); opcode = a & 15; n = b & 127
            if n == 126: n = struct.unpack("!H", self._exact(2))[0]
            elif n == 127: n = struct.unpack("!Q", self._exact(8))[0]
            if n > self.max_frame: raise SearchError("CDP frame exceeds size limit")
            mask = self._exact(4) if b & 128 else None
            payload = self._exact(n)
            if mask: payload = bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
            if opcode == 8: raise BrowserUnavailable("CDP connection closed")
            if opcode == 9: self._send_control(10, payload); continue
            if opcode in (1, 2): chunks.extend(payload)
            elif opcode == 0: chunks.extend(payload)
            if len(chunks) > self.max_frame: raise SearchError("CDP message exceeds size limit")
            if a & 128:
                if opcode not in (1, 0): continue
                return chunks.decode("utf-8")

    def _send_control(self, opcode, data):
        mask = secrets.token_bytes(4)
        self.sock.sendall(bytes([0x80 | opcode, 0x80 | len(data)]) + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(data)))

    def close(self):
        try: self.sock.close()
        except OSError: pass


def _chrome_executable():
    executable=shutil.which('chrome') or shutil.which('google-chrome') or shutil.which('chromium')
    if executable: return executable
    if os.name=='nt':
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe') as key:
                    candidate=winreg.QueryValue(key,None)
                    if Path(candidate).is_file(): return candidate
            except OSError: pass
    roots=[os.environ.get('SCOOP'),str(Path.home()/'scoop')]
    scoop=shutil.which('scoop')
    if scoop: roots.append(str(Path(scoop).parent.parent))
    candidates=[Path(root)/'apps/googlechrome/current/chrome.exe' for root in roots if root]
    for key in ('LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)'):
        if os.environ.get(key): candidates.append(Path(os.environ[key])/'Google/Chrome/Application/chrome.exe')
    for candidate in candidates:
        if candidate.is_file(): return str(candidate)
    raise BrowserUnavailable('Google Chrome was not found; install Chrome to use image search')


class Browser:
    """Owns one tab per search source; never enumerates or attaches to other tabs."""
    def __init__(self, port=9235, headless=False):
        if port not in (9235, 9236): raise BrowserUnavailable("Only the plugin's local CDP ports are allowed")
        self.port = port
        self.headless = headless
        self._process = None
        self._process_owner = None
        self._profile_dir = None
        self._proxy = ''
        self._ws = None
        self._next = 0
        self._targets = {}
        self._sessions = {}
        self._paging = {}
        self._detail_targets = {}
        self._detail_sessions = {}

    def _version(self, timeout=1):
        data = request_bytes(urllib.request.Request(f'http://127.0.0.1:{self.port}/json/version'),
                             timeout=timeout, limit=MAX_HTTP)
        return json.loads(data)

    def _endpoint_ready(self):
        try:
            return bool(self._version().get('webSocketDebuggerUrl'))
        except (OSError, ValueError):
            return False

    def _is_headless_endpoint(self):
        try:
            return 'HeadlessChrome' in self._version().get('User-Agent', '')
        except (OSError, ValueError):
            return False

    def start(self, profile_dir, proxy='', headless=None):
        desired = self.headless if headless is None else headless
        ready = self._endpoint_ready()
        if ready and desired != self.headless:
            if self._process is None:
                raise BrowserUnavailable('Cannot change the mode of a browser owned by another session')
            self.close()
            ready = False
        self._profile_dir = str(profile_dir)
        self._proxy = proxy
        self.headless = desired
        if ready:
            if desired and self._process is None and not self._is_headless_endpoint():
                raise BrowserUnavailable('The background port belongs to a visible browser; it will not be reused')
            return
        if self._ws: self._ws.close();self._ws=None
        self._targets.clear();self._sessions.clear()
        Path(profile_dir).mkdir(parents=True,exist_ok=True)
        command=[_chrome_executable(),'--remote-debugging-port='+str(self.port),'--remote-debugging-address=127.0.0.1','--remote-allow-origins=http://127.0.0.1','--no-first-run','--user-data-dir='+str(profile_dir),'about:blank']
        if self.headless:
            command[1:1] = ['--headless=new', '--window-size=1280,1000']
        if proxy: command.insert(-1,'--proxy-server='+proxy)
        if os.name=='nt':
            startup=subprocess.STARTUPINFO()
            startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow=0 if self.headless else 7
            self._process = subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,startupinfo=startup,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            self._process = subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            self._process_owner = ProcessOwner(self._process)
            end=time.monotonic()+12
            while time.monotonic()<end:
                check_cancelled()
                if self._endpoint_ready(): return
                interruptible_sleep(.25)
        except BaseException:
            self.close()
            raise
        self.close()
        raise BrowserUnavailable('The isolated browser did not start; close its old window and search again')

    def _connect(self):
        if self._ws: return
        try:
            url = self._version(timeout=TIMEOUT).get('webSocketDebuggerUrl')
            self._ws = _WebSocket.connect(url)
        except BrowserUnavailable: raise
        except Exception as exc: raise BrowserUnavailable("Cannot connect to local Chrome CDP endpoint") from exc

    def _command(self, method, params=None, session=None):
        check_cancelled()
        self._connect(); self._next += 1; ident = self._next
        msg = {"id": ident, "method": method, "params": params or {}}
        if session: msg["sessionId"] = session
        try:
            self._ws.send(json.dumps(msg, separators=(",", ":")))
            end = time.monotonic() + TIMEOUT
            while time.monotonic() < end:
                check_cancelled()
                obj = json.loads(self._ws.recv())
                if obj.get("id") == ident:
                    if "error" in obj: raise SearchError("CDP command failed: " + str(obj["error"].get("message", "error"))[:200])
                    return obj.get("result", {})
            raise SearchError("CDP command timed out")
        except Exception:
            # A partial/abandoned response cannot be reused by the next job.
            if self._ws:
                self._ws.close()
                self._ws = None
            raise

    def _ensure_tab(self, source):
        if source not in self._targets:
            target = self._command("Target.createTarget", {"url": "about:blank"}).get("targetId")
            if not target: raise BrowserUnavailable("Chrome did not create a search tab")
            session = self._command("Target.attachToTarget", {"targetId": target, "flatten": True}).get("sessionId")
            self._targets[source], self._sessions[source] = target, session
            self._command("Page.enable", session=session)
            self._command("Runtime.enable", session=session)
        return self._sessions[source]

    def _navigate(self, session, url):
        self._command("Page.navigate", {"url": url}, session)

    def _evaluate(self, session, expression):
        result = self._command("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}, session)
        if result.get("exceptionDetails"): raise SearchError("Page evaluation failed")
        return result.get("result", {}).get("value")

    def search(self, source, query, limit=24):
        source = str(source).lower()
        if source not in ("google", "pinterest"): raise SearchError("source must be google or pinterest")
        if not isinstance(query, str) or not query.strip(): raise SearchError("query must not be empty")
        try: limit = max(1, min(100, int(limit)))
        except (TypeError, ValueError): limit = 24
        self._paging[source] = {'query': query.strip(), 'seen': set(), 'exhausted': True}
        session = self._ensure_tab(source)
        q = urllib.parse.quote_plus(query.strip())
        if source == "google": url = "https://www.google.com/search?udm=2&q=" + q
        else: url = "https://www.pinterest.com/search/pins/?q=" + q
        self._navigate(session, url)
        script = '''(() => {
          const href=location.href, text=(document.body?.innerText||'').slice(0,12000).toLowerCase();
          if (/\\/sorry\\//.test(href) || /unusual traffic|verify you are human|异常流量/.test(text)) return {challenge:true};
          if (new URL(href).searchParams.get('q')!==QUERY) return {items:[]};
          const items=[];
          if (SOURCE==='google') {
            for (const im of (document.getElementById('search')||document).querySelectorAll('img')) {
              const thumbnail=im.currentSrc||im.src;
              if (!thumbnail.startsWith('https://encrypted-tbn') || im.naturalWidth<100 || !im.alt) continue;
              items.push({title:im.alt,thumbnail,detail_url:href});
            }
          } else {
            for (const a of document.querySelectorAll('a[href*="/pin/"]')) {
              const im=a.querySelector('img'); if (!im) continue;
              const thumbnail=im.currentSrc||im.src;
              if (!thumbnail.startsWith('https://i.pinimg.com/') || im.naturalWidth<100) continue;
              items.push({title:im.alt||a.getAttribute('aria-label')||'Pinterest image',thumbnail,detail_url:a.href});
            }
          }
          const login=items.length===0 && !!document.querySelector('input[type="email"],input[type="password"]');
          return {href,items,login};
        })()'''.replace('SOURCE', json.dumps(source)).replace('QUERY', json.dumps(query.strip()))
        end = time.monotonic() + TIMEOUT
        data = None
        while time.monotonic() < end:
            data = self._evaluate(session, script)
            if data and (data.get("challenge") or data.get("items")): break
            interruptible_sleep(0.35)
        if not data: raise SearchError("Search page returned no data")
        if data.get("challenge"): raise VerificationRequired("Provider requires verification or login")
        if data.get('login'): raise VerificationRequired('Pinterest requires login in the test browser')
        results, seen = [], set()
        for item in data.get("items", []):
            detail, thumb = item.get("detail_url", ""), item.get("thumbnail", "")
            if not (detail.startswith("https://") and thumb.startswith("https://")): continue
            key = _result_id(source, thumb)
            if key in seen: continue
            seen.add(key)
            title = str(item.get("title") or "").strip()[:500]
            ident = key
            results.append({"id": ident, "title": title, "thumbnail": thumb, "detail_url": detail, "source": source})
            if len(results) >= limit: break
        self._paging[source] = {"query": query.strip(), "seen": {x["id"] for x in results}, "exhausted": bool(data.get('end'))}
        return results

    def has_more(self, source):
        state = self._paging.get(str(source).lower())
        return bool(state and not state["exhausted"])

    def more(self, source, limit=24):
        source = str(source).lower()
        if source not in ("google", "pinterest") or source not in self._paging: return []
        try: limit = max(1, min(100, int(limit)))
        except (TypeError, ValueError): limit = 24
        state = self._paging[source]
        if state["exhausted"]: return []
        session = self._ensure_tab(source)
        script = '''(() => {
          const href=location.href, text=(document.body?.innerText||'').slice(0,12000).toLowerCase();
          if (/\\/sorry\\//.test(href) || /unusual traffic|verify you are human|异常流量/.test(text)) return {challenge:true};
          const items=[];
          const add=(title,thumbnail,detail_url)=>items.push({title,thumbnail,detail_url});
          if(SOURCE==='google') for(const im of (document.getElementById('search')||document).querySelectorAll('img')){const t=im.currentSrc||im.src;if(t.startsWith('https://encrypted-tbn')&&im.naturalWidth>=100&&im.alt)add(im.alt,t,location.href)}
          else for(const a of document.querySelectorAll('a[href*="/pin/"]')){const im=a.querySelector('img');if(im){const t=im.currentSrc||im.src;if(t.startsWith('https://i.pinimg.com/')&&im.naturalWidth>=100)add(im.alt||a.getAttribute('aria-label')||'Pinterest image',t,a.href)}}
          const bottom=document.documentElement.scrollHeight<=innerHeight+scrollY+8;
          const end=bottom && /no more results|you.ve reached the end|没有更多结果|已显示全部结果/.test(text);
          return {items,end};
        })()'''.replace('SOURCE', json.dumps(source))
        output, collected = [], set()
        # Pinterest can hydrate a non-scrollable initial shell before its feed arrives.
        for attempt in range(10):
            data = self._evaluate(session, script) or {}
            if data.get("challenge"): raise VerificationRequired("Provider requires verification or login")
            for item in data.get("items", []):
                detail, thumb = item.get("detail_url", ""), item.get("thumbnail", "")
                if not detail.startswith("https://") or not thumb.startswith("https://"): continue
                ident = _result_id(source, thumb)
                if ident in state["seen"] or ident in collected: continue
                collected.add(ident)
                output.append({"id":ident,"title":str(item.get("title") or "").strip()[:500],"thumbnail":thumb,"detail_url":detail,"source":source})
                if len(output)>=limit: break
            if data.get('end'):
                state["exhausted"] = True
            if output or state['exhausted']:
                break
            self._evaluate(session, "window.scrollBy(0, Math.max(200, Math.floor(innerHeight*0.8))); true")
            interruptible_sleep(0.35)
        state["seen"].update(x["id"] for x in output)
        return output

    def resolve(self, entry):
        if not isinstance(entry, dict) or entry.get("source") not in ("google", "pinterest"):
            raise SearchError("entry must be a search result")
        source = entry["source"]
        detail = entry.get("detail_url", "")
        parsed=urllib.parse.urlsplit(detail)
        expected='www.google.com' if source=='google' else 'www.pinterest.com'
        if parsed.scheme!='https' or parsed.hostname!=expected or parsed.username or parsed.password:
            raise SearchError('Untrusted detail URL')
        if (source=='google' and parsed.path!='/search') or (source=='pinterest' and not parsed.path.startswith('/pin/')):
            raise SearchError('Unsupported detail page')
        session = self._ensure_tab(source)
        scroll_position = self._evaluate(session, '({x: window.scrollX, y: window.scrollY})') if source == 'google' else None
        if source=='pinterest':
            if source not in self._detail_sessions:
                target=self._command("Target.createTarget",{"url":"about:blank"}).get("targetId")
                if not target: raise BrowserUnavailable("Chrome did not create a detail tab")
                detail_session=self._command("Target.attachToTarget",{"targetId":target,"flatten":True}).get("sessionId")
                self._detail_targets[source],self._detail_sessions[source]=target,detail_session
                self._command("Page.enable",session=detail_session);self._command("Runtime.enable",session=detail_session)
            session=self._detail_sessions[source]
            self._navigate(session,detail)
            # Match the selected asset's file key, not a related picture with a larger size.
            key=urllib.parse.urlsplit(entry.get('thumbnail','')).path.rsplit('/',1)[-1]
            script='''(() => {
              const href=location.href;
              if (href!==DETAIL) return {href};
              const image=[...document.images].find(i=>(i.currentSrc||i.src).includes(KEY)&&i.naturalWidth>=320);
              return {href,url:image?.currentSrc||'',login:!!document.querySelector('input[type="password"]')};
            })()'''.replace('DETAIL',json.dumps(detail)).replace('KEY',json.dumps(key))
        else:
            coordinate_script='''(() => {
              const i=[...document.images].find(i=>(i.currentSrc||i.src)===THUMB);
              if(!i)return null;i.scrollIntoView({block:'center'});
              const r=i.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};
            })()'''.replace('THUMB',json.dumps(entry.get('thumbnail','')))
            point=self._evaluate(session,coordinate_script)
            if not point:
                self._navigate(session,detail)
                end=time.monotonic()+TIMEOUT
                while time.monotonic()<end and not point:
                    interruptible_sleep(0.25);point=self._evaluate(session,coordinate_script)
            if not point: raise SearchError('The selected search result is no longer available; search again')
            for event in ('mousePressed','mouseReleased'):
                self._command('Input.dispatchMouseEvent',{'type':event,'button':'left','buttons':1 if event=='mousePressed' else 0,'clickCount':1,**point},session)
            script='''(() => {
              const href=location.href;
              if (/\\/sorry\\//.test(href)) return {challenge:true};
              const images=[...document.images].filter(i=>i.alt===TITLE && i.naturalWidth>=320 && i.naturalHeight>=240 && i.getBoundingClientRect().width>0 && (i.currentSrc||i.src).startsWith('https://') && !/google|gstatic/.test(new URL(i.currentSrc||i.src).hostname));
              images.sort((a,b)=>b.naturalWidth*b.naturalHeight-a.naturalWidth*a.naturalHeight);
              return {href,url:images[0]?.currentSrc||''};
            })()'''.replace('TITLE',json.dumps(entry.get('title','')))
        end=time.monotonic()+TIMEOUT
        value={}
        while time.monotonic()<end:
            value=self._evaluate(session,script) or {}
            if value.get('challenge') or value.get('url'): break
            interruptible_sleep(0.3)
        if value.get('challenge') or value.get('login'):
            raise VerificationRequired('Provider requires verification or login')
        chosen=value.get('url','')
        if not chosen.startswith('https://'): raise SearchError('Could not resolve the selected large image')
        if isinstance(scroll_position, dict) and all(isinstance(scroll_position.get(key), (int, float)) for key in ('x', 'y')):
            self._evaluate(session, 'window.scrollTo(' + json.dumps(scroll_position['x']) + ',' + json.dumps(scroll_position['y']) + '); true')
        return {'url':chosen,'referer':value.get('href') or detail,'title':str(entry.get('title') or '')[:500]}

    def show(self):
        if self.headless:
            if self._profile_dir is None:
                raise BrowserUnavailable('Search once before opening Google verification')
            query = self._paging.get('google', {}).get('query', '')
            self.start(self._profile_dir, self._proxy, headless=False)
            session = self._ensure_tab('google')
            self._navigate(session, 'https://www.google.com/search?' + urllib.parse.urlencode({'q': query, 'udm': '2'}))
        if not self._targets:
            session=self._ensure_tab('google')
            self._navigate(session,'https://www.google.com/')
        target = next(reversed(self._targets.values()))
        info=self._command('Browser.getWindowForTarget',{'targetId':target})
        if 'windowId' in info:
            self._command('Browser.setWindowBounds',{'windowId':info['windowId'],'bounds':{'windowState':'normal'}})
        self._command("Target.activateTarget", {"targetId": target})
        return True

    def close(self, deadline=None):
        end = deadline if deadline is not None else time.monotonic()+2
        targets = list(self._targets.values()) + list(self._detail_targets.values())
        self._targets.clear(); self._sessions.clear()
        self._detail_targets.clear(); self._detail_sessions.clear(); self._paging.clear()
        process, self._process = self._process, None
        try:
            with task_scope(Token(max(.001, min(.3, end-time.monotonic())))):
                if process is not None:
                    self._command('Browser.close')
                else:
                    for target in targets:
                        self._command('Target.closeTarget', {'targetId': target})
        except Exception:
            pass
        finally:
            if self._ws:
                self._ws.close()
                self._ws = None
        if self._process_owner is not None:
            self._process_owner.close()
            self._process_owner = None
        if process is not None:
            try:
                process.wait(timeout=max(0, min(.3, end-time.monotonic())))
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=max(0, min(.3, end-time.monotonic())))
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=max(0, end-time.monotonic()))
                    except subprocess.TimeoutExpired:
                        pass
