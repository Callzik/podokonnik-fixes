import argparse
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


parser = argparse.ArgumentParser()
parser.add_argument("source", type=Path)
parser.add_argument("compiler")
args = parser.parse_args()
app = (args.source / "app.h").read_text(encoding="utf-8")

test = r"""
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
using namespace std;

struct WpItem {
    string id, source, kind;
    wstring path;
    int progress = -1;
    bool ready = true;
};
static vector<int> gMons{0, 1}, gWpWins;
static vector<string> gWpMon, savedMon;
static string gWpCurrent, gConvId;
static bool gConvBusy = false;
static void InterlockedExchange(bool* value, int next) { *value = next != 0; }
static bool converted = false;
static WpItem local{"local", "file", "image", L"image"};
static WpItem video{"video", "file", "video", L"video"};
static WpItem builtin{"builtin:0", "builtin", "video", L"builtin"};
static int queued = -1, rebuilds = 0;
static WpItem* findItem(const string& id) {
    for (auto* item : {&local, &video, &builtin}) if (item->id == id) return item;
    return nullptr;
}
static bool itemReady(const WpItem& item) { return item.ready; }
static bool videoNeedsConvert(const wstring& path) { return path == L"video"; }
static wstring convertedPath(const wstring&) { return L"mp4"; }
static bool fileExists(const wstring&) { return converted; }
static bool wpUrlFor(const WpItem& item, wstring&, vector<wstring>&) {
    if (!gConvBusy) { gConvBusy = true; gConvId = item.id; }
    return false;
}
static wstring W16(const string& s) { return wstring(s.begin(), s.end()); }
static void cfgSetStr(const wchar_t*, const wstring&) {}
static void wpRebuild() { ++rebuilds; }
static void saveWpMon() { savedMon = gWpMon; }
static void queueVideo(int id) { queued = id; }
static void appPushWallpapers() {}
static void appPushState() {}
static void appToast(const char*) {}
"""
start = app.index("static std::string gWpPending;")
end = app.find("\n\n", start)
test += app[start:end] + "\n"
for name, following in [("wpStartItem", "wpSetMuted")]:
    start = app.index("static void " + name + "(")
    end = app.index("static void " + following + "(", start)
    test += app[start:end]
for macro, next_branch in [("WM_CONVDONE", "WM_WPPROGRESS"), ("WM_WPREADY", None)]:
    start = app.index("    if (msg == " + macro + ") {")
    end = app.index("    if (msg == " + next_branch + ")", start) if next_branch else app.index("    return false;", start)
    test += f"\nstatic bool handle{macro}(int wp, int lp) {{\n"
    test += "    const int msg = 0, " + macro + " = 0;\n" + app[start:end] + "    return false;\n}\n"

test += r"""
static int failures = 0;
static void check(bool ok, const char* scenario) {
    printf("%s %s\n", ok ? "PASS" : "FAIL", scenario);
    failures += !ok;
}
int main() {
    const vector<string> overrides{"old-left", "old-right"};
    gWpCurrent = "old-all";
    gWpMon = savedMon = overrides;
    wpApplyOn("missing", -1);
    check(gWpMon == overrides && savedMon == overrides, "missing selection keeps per-monitor settings");

    gWpMon = savedMon = {"old-left", "old-right", "unplugged"};
    wpApplyOn("local", 2);
    check(gWpMon[2] == "unplugged" && savedMon[2] == "unplugged", "selection for disconnected monitor is ignored");

    gWpCurrent = "old-all";
    gWpMon = savedMon = overrides;
    builtin.ready = false;
    wpApplyOn(builtin.id, 1);
    check(queued == 0 && gWpMon == overrides, "download preserves current wallpaper while waiting");
    builtin.ready = true;
    handleWM_WPREADY(0, 1);
    check(gWpCurrent == "old-all" && gWpMon == vector<string>{"old-left", "builtin:0"} && savedMon == gWpMon,
          "download applies only on the chosen monitor");

    gWpCurrent = "old-all";
    gWpMon = savedMon = overrides;
    builtin.ready = false;
    wpApplyOn(builtin.id, -1);
    handleWM_WPREADY(0, 0);
    check(gWpCurrent == "old-all" && gWpMon == overrides && savedMon == overrides,
          "failed download keeps current wallpapers and settings");
    wpApplyOn(builtin.id, -1);
    builtin.ready = true;
    handleWM_WPREADY(0, 1);
    check(gWpCurrent == builtin.id && gWpMon.empty() && savedMon.empty(),
          "successful all-monitor application clears overrides");

    gWpMon = savedMon = overrides;
    wpApplyOn(video.id, 1);
    check(gWpMon == overrides && savedMon == overrides, "conversion keeps existing wallpaper while waiting");
    converted = true;
    handleWM_CONVDONE(1, 0);
    check(gWpMon == vector<string>{"old-left", "video"} && savedMon == gWpMon,
          "converted wallpaper applies only on the chosen monitor");

    gWpCurrent.clear();
    const int before = rebuilds;
    wpRestart();
    check(rebuilds == before + 1, "per-monitor wallpapers rebuild after desktop reset");

    builtin.ready = false;
    wpApplyOn(builtin.id, 1);
    gMons.resize(1);
    builtin.ready = true;
    handleWM_WPREADY(0, 1);
    check(gWpCurrent.empty() && gWpMon == vector<string>{"old-left", "video"},
          "download completion ignores a monitor disconnected during download");

    builtin.ready = false;
    wpApplyOn(builtin.id, -1);
    wpApplyOn(local.id, 0);
    builtin.ready = true;
    handleWM_WPREADY(0, 1);
    check(gWpCurrent == local.id && gWpMon.empty(), "superseded download cannot replace the latest selection");
    return failures ? 1 : 0;
}
"""

with TemporaryDirectory() as tmp:
    source = Path(tmp) / "wallpapers.cpp"
    exe = Path(tmp) / "wallpapers.exe"
    source.write_text(test, encoding="utf-8")
    subprocess.run([args.compiler, "-std=c++17", "-static", source, "-o", exe], check=True)
    raise SystemExit(subprocess.run([exe]).returncode)
