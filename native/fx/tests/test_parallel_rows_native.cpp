#include "tfm_processing.h"
#include <QCoreApplication>
#include <atomic>
#include <chrono>
#include <iostream>
#include <thread>

int main(int argc, char **argv) {
    QCoreApplication app(argc,argv);
    qputenv("TFM_THREADS","2");
    std::atomic<bool> blocked{false}, release{false}, complete{false};
    std::thread unrelated([&] {
        tfm::parallelRows(2,[&](int first,int) {
            if (first == 0) {
                blocked = true;
                while (!release) std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
        });
    });
    while (!blocked) std::this_thread::yield();
    std::thread own([&] {
        tfm::parallelRows(2,[&](int,int) {
            // Nested requests must not wait on their own occupied pool.
            tfm::parallelRows(2,[](int,int) {});
        });
        complete = true;
    });
    const auto deadline = std::chrono::steady_clock::now()+std::chrono::seconds(1);
    while (!complete && std::chrono::steady_clock::now()<deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    const bool independent = complete;
    release = true;
    unrelated.join(); own.join();
    if (!independent) { std::cerr << "Waited for unrelated work or nested pool deadlock\n"; return 1; }
    std::cout << "Independent and nested row scheduling PASS\n";
}
