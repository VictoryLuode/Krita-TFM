#pragma once

#include "tfm_statistical_transfer.h"
#include <QByteArray>
#include <QDataStream>
#include <QIODevice>

namespace tfm::statistical {

inline QByteArray encodeProfile(const Profile &profile)
{
    if (!profile.valid) return {};
    QByteArray bytes;
    QDataStream stream(&bytes, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream << quint32(0x46534d33);
    for (double value : profile.quantiles) stream << value;
    for (double value : profile.quantilesA) stream << value;
    for (double value : profile.quantilesB) stream << value;
    const auto write = [&](const Moments &m) {
        stream << m.weight << m.meanA << m.meanB << m.varA << m.covAB << m.varB;
    };
    write(profile.global);
    for (const auto &band : profile.bands) write(band);
    return bytes;
}

inline Profile decodeProfile(const QByteArray &bytes)
{
    Profile profile;
    if (bytes.size() != 4+8*(kQuantiles+6*(kBands+1))
        && bytes.size() != 4+8*(3*kQuantiles+6*(kBands+1))) return profile;
    QDataStream stream(bytes);
    stream.setByteOrder(QDataStream::LittleEndian);
    quint32 magic = 0;
    stream >> magic;
    if (magic != 0x46534d32 && magic != 0x46534d33) return {};
    auto readQuantiles = [&stream](std::array<double, kQuantiles> &values, double low) {
        double previous = low;
        for (double &value : values) {
            stream >> value;
            if (!std::isfinite(value) || value < low || value > 1 || value < previous) return false;
            previous = value;
        }
        return true;
    };
    if (!readQuantiles(profile.quantiles, 0)) return {};
    if (magic == 0x46534d33) {
        if (!readQuantiles(profile.quantilesA, -1)
            || !readQuantiles(profile.quantilesB, -1)) return {};
    }
    const auto read = [&](Moments &m) {
        stream >> m.weight >> m.meanA >> m.meanB >> m.varA >> m.covAB >> m.varB;
        return std::isfinite(m.weight) && m.weight > 0
            && std::isfinite(m.meanA) && std::abs(m.meanA) <= 1
            && std::isfinite(m.meanB) && std::abs(m.meanB) <= 1
            && std::isfinite(m.varA) && m.varA >= 0 && m.varA <= 1
            && std::isfinite(m.varB) && m.varB >= 0 && m.varB <= 1
            && std::isfinite(m.covAB) && std::abs(m.covAB) <= 1;
    };
    if (!read(profile.global)) return {};
    for (auto &band : profile.bands) if (!read(band)) return {};
    profile.valid = stream.status() == QDataStream::Ok && stream.atEnd();
    return profile;
}

} // namespace tfm::statistical
