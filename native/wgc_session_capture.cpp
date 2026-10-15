// DEFAULT-OFF experiment: persistent HWND-only Windows Graphics Capture.
// Not wired into production. Requires source and frozen Windows evidence first.
// Design references (not vendored code): robmikh/Win32CaptureSample and
// NiiightmareXD/windows-capture. See the project's third-party/research notes.
// The OS frame pool necessarily owns a full TARGET WINDOW GPU surface. Only
// the verified client ROI is copied to a staging texture or read into CPU RAM.
// No monitor items, process-memory reads, injection, hooks or border suppression.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <dwmapi.h>
#include <d3d11.h>
#include <dxgi.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Metadata.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <limits>
#include <memory>
#include <string>
#include <vector>

using namespace winrt;
using namespace winrt::Windows::Graphics::Capture;
using namespace winrt::Windows::Graphics::DirectX;
using namespace winrt::Windows::Graphics::DirectX::Direct3D11;
using winrt::Windows::Foundation::Metadata::ApiInformation;

namespace {
constexpr int unsupported = 10, timed_out = 11, stale = 12, protected_content = 13, failed = 14;
constexpr uint64_t pixel_budget = 16000000;
// Failure metadata protocol on stderr. All strings are static IDs, all
// values are numeric dimensions/styles/clocks; never titles, paths, IDs or pixels.
// stdout remains exclusively the exact ROI pixel protocol on successful capture.
struct ClockDiagnostic {
    bool present = false;
    int64_t qpc_counter = 0, qpc_frequency = 0, cutoff_100ns = 0,
        frame_100ns = 0, observed_now_100ns = 0, previous_frame_100ns = 0;
};
struct Diagnostic {
    char const* phase = "startup";
    int64_t observed[4]{}, expected[4]{}, window_rect[4]{}, frame_rect[4]{};
    uint32_t style = 0, extended_style = 0;
    ClockDiagnostic clock;
} diagnostic;
void phase(char const* value) {
    diagnostic.phase = value;
    std::fill_n(diagnostic.observed, 4, int64_t(0));
    std::fill_n(diagnostic.expected, 4, int64_t(0));
    diagnostic.style = diagnostic.extended_style = 0;
    diagnostic.clock = {};
}
void frame_clock(int64_t cutoff, int64_t frame, int64_t previous_frame) {
    // A nonpositive frame short-circuits the existing predicate without QPC.
    // Its raw counter/frequency/observed-now stay zero: unsampled, not a QPC error.
    diagnostic.clock = {true, 0, 0, cutoff, frame, 0, previous_frame};
}
void dimensions(int64_t x, int64_t y, int64_t width, int64_t height,
                int64_t ex = 0, int64_t ey = 0, int64_t ew = 0, int64_t eh = 0) {
    diagnostic.observed[0] = x; diagnostic.observed[1] = y;
    diagnostic.observed[2] = width; diagnostic.observed[3] = height;
    diagnostic.expected[0] = ex; diagnostic.expected[1] = ey;
    diagnostic.expected[2] = ew; diagnostic.expected[3] = eh;
}
struct SensitivePixels : std::vector<uint8_t> {
    ~SensitivePixels() { if (!empty()) SecureZeroMemory(data(), size()); }
};
struct Failure { int code; char const* check; };
void require(bool value, int code = stale, char const* check = "invariant") {
    if (!value) throw Failure{code, check};
}
void report_failure(int code, char const* check, uint32_t hresult = 0) noexcept {
    // One bounded write, no logging dependency, no exception text or system data.
    // The parent drains this pipe concurrently within the same process deadline.
    char data[1024]{};
    char clock_data[384]{};
    if (diagnostic.clock.present && code == stale && std::strcmp(check, "frame-timestamp") == 0 &&
            (std::strcmp(diagnostic.phase, "frame-wait") == 0 ||
             std::strcmp(diagnostic.phase, "validate-idle") == 0)) {
        auto const& clock = diagnostic.clock;
        int clock_count = std::snprintf(clock_data, sizeof(clock_data),
            ",\"clock\":{\"qpc_counter\":%lld,\"qpc_frequency\":%lld,\"cutoff_100ns\":%lld,"
            "\"frame_100ns\":%lld,\"observed_now_100ns\":%lld,\"previous_frame_100ns\":%lld}",
            static_cast<long long>(clock.qpc_counter), static_cast<long long>(clock.qpc_frequency),
            static_cast<long long>(clock.cutoff_100ns), static_cast<long long>(clock.frame_100ns),
            static_cast<long long>(clock.observed_now_100ns), static_cast<long long>(clock.previous_frame_100ns));
        if (clock_count <= 0 || clock_count >= int(sizeof(clock_data))) return;
    }
    int count = std::snprintf(data, sizeof(data),
        "{\"schema_version\":1,\"code\":%d,\"phase\":\"%s\",\"check\":\"%s\","
        "\"hresult\":%u,\"observed\":[%lld,%lld,%lld,%lld],"
        "\"expected\":[%lld,%lld,%lld,%lld],\"window_rect\":[%lld,%lld,%lld,%lld],"
        "\"frame_rect\":[%lld,%lld,%lld,%lld],\"style\":%u,\"extended_style\":%u%s}\n",
        code, diagnostic.phase, check, static_cast<unsigned int>(hresult),
        static_cast<long long>(diagnostic.observed[0]), static_cast<long long>(diagnostic.observed[1]),
        static_cast<long long>(diagnostic.observed[2]), static_cast<long long>(diagnostic.observed[3]),
        static_cast<long long>(diagnostic.expected[0]), static_cast<long long>(diagnostic.expected[1]),
        static_cast<long long>(diagnostic.expected[2]), static_cast<long long>(diagnostic.expected[3]),
        static_cast<long long>(diagnostic.window_rect[0]), static_cast<long long>(diagnostic.window_rect[1]),
        static_cast<long long>(diagnostic.window_rect[2]), static_cast<long long>(diagnostic.window_rect[3]),
        static_cast<long long>(diagnostic.frame_rect[0]), static_cast<long long>(diagnostic.frame_rect[1]),
        static_cast<long long>(diagnostic.frame_rect[2]), static_cast<long long>(diagnostic.frame_rect[3]),
        static_cast<unsigned int>(diagnostic.style), static_cast<unsigned int>(diagnostic.extended_style), clock_data);
    if (count > 0 && count < int(sizeof(data))) {
        DWORD written = 0;
        WriteFile(GetStdHandle(STD_ERROR_HANDLE), data, DWORD(count), &written, nullptr);
    }
}
// Seven fixed 3-byte checkpoints; failure diagnostics surface them only for
// nonzero exit after complete pipe cleanup. They identify the last reached
// main-thread checkpoint, not the faulting thread/operation or a crash cause. No exception handling,
// retries, teardown reordering or success conversion. The existing parent cap
// covers the entire transcript: 21 bytes plus the bounded failure JSON.
enum class ShutdownStage : char {
    frame_arrived_revoke = '1', item_closed_revoke = '2', session_close = '3',
    pool_close = '4', local_release = '5', apartment_uninit = '6', process_return = '7'
};
void shutdown_checkpoint(ShutdownStage stage) noexcept {
    char const data[]{'S', static_cast<char>(stage), '\n'};
    DWORD written = 0;
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), data, DWORD(sizeof(data)), &written, nullptr);
}
struct Handle {
    HANDLE value = nullptr;
    explicit Handle(HANDLE handle) : value(handle) {}
    ~Handle() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); }
    Handle(Handle const&) = delete;
    Handle& operator=(Handle const&) = delete;
};
struct CaptureSignal {
    Handle event{CreateEventW(nullptr, FALSE, FALSE, nullptr)};
    std::atomic<bool> closed{false};
};
// No ROI is supplied at startup. The target, parent and overlay registration
// remain immutable; only an individually validated request can authorize pixels.
constexpr DWORD watchdog_ms = 25, idle_lease_ms = 4000;
constexpr uint32_t required_overlay_style = WS_EX_LAYERED | WS_EX_NOACTIVATE |
    WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_TRANSPARENT;
struct Input {
    HWND hwnd;
    DWORD pid;
    uint64_t created;
    int x, y, width, height;
    DWORD parent_pid;
    uint64_t parent_created;
    HWND overlay;
    uint32_t overlay_style;
    uint64_t overlay_generation, generation;
    HANDLE parent = nullptr;
};
#pragma pack(push, 1)
struct Request {
    char magic[8];
    uint32_t opcode, size;
    uint64_t id, generation;
    int32_t left, top, width, height;
    uint32_t wait_ms, reserved;
};
struct Response {
    char magic[8];
    uint32_t status, phase;
    uint64_t id, generation;
    uint32_t width, height, length, reserved;
    int64_t cutoff, frame_time;
};
struct Idle {
    char magic[8];
    uint64_t id, generation;
    int64_t entered;
};
#pragma pack(pop)
static_assert(sizeof(Request) == 56);
static_assert(sizeof(Response) == 64);
static_assert(sizeof(Idle) == 32);
struct Geometry { RECT frame; RECT window; POINT origin; RECT client; };
constexpr bool same(RECT const& a, RECT const& b) {
    return a.left == b.left && a.top == b.top && a.right == b.right && a.bottom == b.bottom;
}
// WGC geometry selection is exact, never a guessed border/padding offset.
// GetWindowRect includes invisible resize borders; DWM reports visible bounds.
// Both are physical here because this process establishes PMv2 before querying.
// https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowrect
// 0 = no exact model, 1 = Win32 outer bounds, 2 = DWM visible bounds,
// -1 = equal extents with inconsistent origins, which must not be guessed.
constexpr int capture_model(RECT const& window, RECT const& frame, int64_t width, int64_t height) {
    bool outer = width > 0 && height > 0 &&
        int64_t(window.right) - window.left == width && int64_t(window.bottom) - window.top == height;
    bool visible = width > 0 && height > 0 &&
        int64_t(frame.right) - frame.left == width && int64_t(frame.bottom) - frame.top == height;
    if (outer && visible && !same(window, frame)) return -1;
    return outer ? 1 : (visible ? 2 : 0);
}
// The frame's content can be smaller than the item-sized pool allocation.
// It must still exactly name one original rectangle; arbitrary smaller frames
// and ambiguous origins are not valid mappings. -2 means content would be clipped.
constexpr int content_model(RECT const& window, RECT const& frame, int64_t pool_width,
                            int64_t pool_height, int64_t width, int64_t height) {
    int model = capture_model(window, frame, width, height);
    if (model <= 0) return model;
    return width <= pool_width && height <= pool_height ? model : -2;
}
constexpr bool roi_inside(int64_t left, int64_t top, int64_t width, int64_t height,
                          int64_t extent_width, int64_t extent_height) {
    return left >= 0 && top >= 0 && width > 0 && height > 0 &&
        left <= extent_width && top <= extent_height &&
        width <= extent_width - left && height <= extent_height - top;
}
// These assertions execute in the mandatory native helper build. They cover
// the actual run-17 coordinates, identical borderless bounds, ambiguity and
// negative desktop coordinates without requiring capture access or pixels.
static_assert(capture_model({22, 30, 358, 309}, {29, 30, 351, 302}, 336, 279) == 1);
static_assert(capture_model({22, 30, 358, 309}, {29, 30, 351, 302}, 322, 272) == 2);
static_assert(capture_model({22, 30, 358, 309}, {29, 30, 351, 302}, 335, 279) == 0);
static_assert(capture_model({22, 30, 358, 309}, {29, 30, 351, 302}, 336, 278) == 0);
static_assert(capture_model({30, 30, 350, 270}, {30, 30, 350, 270}, 320, 240) == 1);
static_assert(capture_model({30, 30, 350, 270}, {31, 30, 351, 270}, 320, 240) == -1);
static_assert(capture_model({30, 30, 350, 270}, {30, 31, 350, 271}, 320, 240) == -1);
static_assert(capture_model({-978, -30, -642, 249}, {-971, -30, -649, 242}, 336, 279) == 1);
static_assert(capture_model({30, 30, 30, 270}, {30, 30, 30, 270}, 0, 240) == 0);
// Actual run-18: item/pool is Win32 outer, valid content is DWM visible.
static_assert(content_model({22, 30, 358, 309}, {29, 30, 351, 302}, 336, 279, 322, 272) == 2);
static_assert(content_model({22, 30, 358, 309}, {29, 30, 351, 302}, 336, 279, 336, 279) == 1);
static_assert(content_model({22, 30, 358, 309}, {29, 30, 351, 302}, 322, 272, 336, 279) == -2);
static_assert(content_model({22, 30, 358, 309}, {29, 30, 351, 302}, 336, 279, 321, 272) == 0);
static_assert(content_model({30, 30, 350, 270}, {31, 30, 351, 270}, 320, 240, 320, 240) == -1);
static_assert(content_model({30, 30, 350, 270}, {30, 30, 350, 270}, 320, 240, 320, 240) == 1);
static_assert(roi_inside(81, 91, 160, 120, 322, 272));
static_assert(roi_inside(1, 31, 320, 240, 322, 272));
static_assert(roi_inside(300, 240, 32, 32, 336, 279));
static_assert(!roi_inside(300, 240, 32, 32, 322, 272));  // Exclude pool padding.
static_assert(!roi_inside(-1, 0, 32, 32, 322, 272));
static_assert(!roi_inside(0, 260, 32, 16, 322, 272));
bool intersects(RECT const& a, RECT const& b) {
    return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}
int64_t number(wchar_t const* text) {
    require(text && *text, failed);
    wchar_t* end = nullptr;
    errno = 0;
    auto result = _wcstoi64(text, &end, 10);
    require(!errno && end != text && !*end, failed);
    return result;
}
Input parse(int argc, wchar_t** argv) {
    require(argc == 15 && std::wstring(argv[1]) == L"--session-v2", failed);
    int64_t n[13];
    for (int i = 0; i < 13; ++i) n[i] = number(argv[i + 2]);
    require(n[0] > 0 && n[1] > 0 && n[1] <= UINT32_MAX && n[2] > 0, failed);
    for (int i = 3; i <= 6; ++i)
        require(n[i] >= INT32_MIN && n[i] <= INT32_MAX, failed);
    require(n[5] >= 64 && n[6] >= 64 && uint64_t(n[5]) * n[6] <= pixel_budget, failed);
    require(n[3] + n[5] <= INT32_MAX && n[4] + n[6] <= INT32_MAX, failed);
    require(n[7] > 0 && n[7] <= UINT32_MAX && n[8] > 0, failed);
    require(n[9] >= 0 && n[10] >= 0 && n[10] <= UINT32_MAX && n[11] >= 0 && n[12] > 0, failed);
    require((n[9] == 0 && n[10] == 0 && n[11] == 0) ||
            (n[9] > 0 && n[11] > 0 &&
             (uint32_t(n[10]) & required_overlay_style) == required_overlay_style), failed);
    require(n[9] != n[0], failed);
    return {reinterpret_cast<HWND>(n[0]), DWORD(n[1]), uint64_t(n[2]),
            int(n[3]), int(n[4]), int(n[5]), int(n[6]), DWORD(n[7]), uint64_t(n[8]),
            reinterpret_cast<HWND>(n[9]), uint32_t(n[10]), uint64_t(n[11]), uint64_t(n[12])};
}
uint64_t creation_time(DWORD pid) {
    // Metadata only. Never request VM_READ, VM_WRITE or PROCESS_ALL_ACCESS.
    Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid));
    require(process.value != nullptr, stale, "process-open");
    FILETIME created{}, exited{}, kernel{}, user{};
    require(GetProcessTimes(process.value, &created, &exited, &kernel, &user) != FALSE, stale, "process-times");
    return (uint64_t(created.dwHighDateTime) << 32) | created.dwLowDateTime;
}
uint64_t handle_creation(HANDLE process) {
    FILETIME created{}, exited{}, kernel{}, user{};
    require(GetProcessTimes(process, &created, &exited, &kernel, &user) != FALSE, stale, "process-times");
    return (uint64_t(created.dwHighDateTime) << 32) | created.dwLowDateTime;
}
void validate_parent(Input const& p) {
    require(p.parent && WaitForSingleObject(p.parent, 0) == WAIT_TIMEOUT &&
            handle_creation(p.parent) == p.parent_created, stale, "parent-lifetime");
}
std::wstring overlay_property(uint64_t generation) {
    return L"VGA.WGC.SessionV2.Overlay." + std::to_wstring(generation);
}
void validate_overlay(Input const& p) {
    // 0x11 is true exclusion only on Windows 10 build 19041+, with DWM active.
    // Read-only feature detection avoids undocumented version APIs and manifest
    // dependent GetVersionEx results. This contract arrived with UniversalApi v10.
    BOOL composition = FALSE;
    require(ApiInformation::IsApiContractPresent(L"Windows.Foundation.UniversalApiContract", 10) &&
            SUCCEEDED(DwmIsCompositionEnabled(&composition)) && composition, stale, "overlay-support");
    DWORD owner = 0, affinity = 0;
    require(IsWindow(p.overlay) && GetAncestor(p.overlay, GA_ROOT) == p.overlay &&
            GetWindowThreadProcessId(p.overlay, &owner) && owner == p.parent_pid, stale, "overlay-owner");
    require(uint64_t(reinterpret_cast<uintptr_t>(GetPropW(p.overlay,
            overlay_property(p.overlay_generation).c_str()))) == p.overlay_generation,
            stale, "overlay-generation");
    auto style = uint32_t(GetWindowLongPtrW(p.overlay, GWL_EXSTYLE));
    require(style == p.overlay_style && (style & required_overlay_style) == required_overlay_style,
            stale, "overlay-style");
    require(GetWindowDisplayAffinity(p.overlay, &affinity) && affinity == 0x11,
            stale, "overlay-affinity");
}
struct ZOrder {
    HWND target; RECT client; Input const* idle = nullptr;
    bool found = false, blocked = false, unreadable = false;
};
BOOL CALLBACK check_above(HWND hwnd, LPARAM pointer) {
    auto& scope = *reinterpret_cast<ZOrder*>(pointer);
    if (hwnd == scope.target) { scope.found = true; return FALSE; }
    if (!IsWindowVisible(hwnd) || IsIconic(hwnd)) return TRUE;
    DWORD cloaked = 0;
    if (SUCCEEDED(DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, &cloaked, sizeof(cloaked))) && cloaked)
        return TRUE;
    RECT other{};
    if (!GetWindowRect(hwnd, &other)) {
        scope.blocked = scope.unreadable = true; return FALSE;
    }
    if (intersects(scope.client, other)) {
        // CPU checks always have idle == nullptr. No PID-wide exemption exists.
        // Validate the registered HWND again at the precise exemption point.
        if (scope.idle && hwnd == scope.idle->overlay) {
            try { validate_overlay(*scope.idle); return TRUE; }
            catch (...) { scope.blocked = true; return FALSE; }
        }
        dimensions(other.left, other.top, int64_t(other.right) - other.left,
                   int64_t(other.bottom) - other.top, scope.client.left, scope.client.top,
                   int64_t(scope.client.right) - scope.client.left, int64_t(scope.client.bottom) - scope.client.top);
        diagnostic.style = uint32_t(GetWindowLongPtrW(hwnd, GWL_STYLE));
        diagnostic.extended_style = uint32_t(GetWindowLongPtrW(hwnd, GWL_EXSTYLE));
        scope.blocked = true; return FALSE;
    }
    return TRUE;
}
Geometry validate(Input const& p, Geometry const* expected = nullptr, bool idle = false) {
    validate_parent(p);
    if (p.overlay) {
        validate_overlay(p);
        // CPU authorization requires the registered overlay to be hidden even
        // when it is outside the client or below the target in z-order.
        if (!idle) require(!IsWindowVisible(p.overlay), stale, "overlay-hidden");
    }
    require(IsWindow(p.hwnd) && IsWindowVisible(p.hwnd) && !IsIconic(p.hwnd), stale, "window-visible");
    require(GetAncestor(p.hwnd, GA_ROOT) == p.hwnd &&
            GetAncestor(GetForegroundWindow(), GA_ROOT) == p.hwnd, stale, "foreground-root");
    DWORD pid = 0;
    require(GetWindowThreadProcessId(p.hwnd, &pid) != 0 && pid == p.pid, stale, "window-process");
    require(creation_time(pid) == p.created, stale, "process-created");
    DWORD cloaked = 0, affinity = 0;
    require(SUCCEEDED(DwmGetWindowAttribute(p.hwnd, DWMWA_CLOAKED, &cloaked, sizeof(cloaked))) && !cloaked, stale, "window-uncloaked");
    // This query is not available for every window style. A known protection
    // is always denied; WGC denial/blank output is never retried through GDI.
    if (GetWindowDisplayAffinity(p.hwnd, &affinity)) require(!affinity, protected_content, "display-affinity");
    Geometry g{};
    require(GetClientRect(p.hwnd, &g.client) && ClientToScreen(p.hwnd, &g.origin), stale, "client-query");
    dimensions(g.origin.x, g.origin.y, g.client.right, g.client.bottom, p.x, p.y, p.width, p.height);
    require(g.client.left == 0 && g.client.top == 0 && g.client.right == p.width &&
            g.client.bottom == p.height && g.origin.x == p.x && g.origin.y == p.y, stale, "client-geometry");
    require(SUCCEEDED(DwmGetWindowAttribute(p.hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, &g.frame, sizeof(g.frame))), stale, "frame-query");
    int64_t fw = int64_t(g.frame.right) - g.frame.left, fh = int64_t(g.frame.bottom) - g.frame.top;
    diagnostic.frame_rect[0] = g.frame.left; diagnostic.frame_rect[1] = g.frame.top;
    diagnostic.frame_rect[2] = fw; diagnostic.frame_rect[3] = fh;
    require(GetWindowRect(p.hwnd, &g.window), stale, "window-query");
    int64_t ww = int64_t(g.window.right) - g.window.left, wh = int64_t(g.window.bottom) - g.window.top;
    diagnostic.window_rect[0] = g.window.left; diagnostic.window_rect[1] = g.window.top;
    diagnostic.window_rect[2] = ww; diagnostic.window_rect[3] = wh;
    dimensions(g.window.left, g.window.top, ww, wh, p.x, p.y, p.width, p.height);
    require(ww > 0 && wh > 0 && uint64_t(ww) <= pixel_budget / uint64_t(wh), stale, "window-budget");
    require(p.x >= g.window.left && p.y >= g.window.top &&
            int64_t(p.x) + p.width <= g.window.right && int64_t(p.y) + p.height <= g.window.bottom,
            stale, "client-in-window");
    dimensions(g.frame.left, g.frame.top, fw, fh, p.x, p.y, p.width, p.height);
    require(fw > 0 && fh > 0 && uint64_t(fw) <= pixel_budget / uint64_t(fh), stale, "frame-budget");
    require(p.x >= g.frame.left && p.y >= g.frame.top &&
            int64_t(p.x) + p.width <= g.frame.right && int64_t(p.y) + p.height <= g.frame.bottom, stale, "client-in-frame");
    if (expected) require(same(g.frame, expected->frame) && same(g.window, expected->window) &&
                          same(g.client, expected->client) &&
                          g.origin.x == expected->origin.x && g.origin.y == expected->origin.y, stale, "geometry-stable");
    RECT bounds{p.x, p.y, p.x + p.width, p.y + p.height};
    MONITORINFO monitor{sizeof(monitor)};
    auto selected = MonitorFromRect(&bounds, MONITOR_DEFAULTTONULL);
    require(selected && GetMonitorInfoW(selected, &monitor) &&
            monitor.rcMonitor.left <= bounds.left && monitor.rcMonitor.top <= bounds.top &&
            bounds.right <= monitor.rcMonitor.right && bounds.bottom <= monitor.rcMonitor.bottom, stale, "client-on-monitor");
    ZOrder order{p.hwnd, bounds, idle ? &p : nullptr};
    EnumWindows(check_above, reinterpret_cast<LPARAM>(&order));
    require(!order.blocked, stale, order.unreadable ? "occluder-query" : "occluder-overlap");
    require(order.found, stale, "zorder-target");
    return g;
}
constexpr int64_t qpc_ticks_100ns(int64_t counter, int64_t frequency, bool round_up) {
    auto whole = counter / frequency;
    auto fraction = counter % frequency;
    // Divide before multiplying; remainder is bounded by the checked frequency.
    return whole * 10000000 + (fraction * 10000000 +
        (round_up ? frequency - 1 : 0)) / frequency;
}
// Exercise the actual conversion during the mandatory native helper build.
static_assert(qpc_ticks_100ns(1, 1000000000, false) == 0);
static_assert(qpc_ticks_100ns(1, 1000000000, true) == 1);
static_assert(qpc_ticks_100ns(10000001, 10000000, false) == 10000001);
static_assert(qpc_ticks_100ns(10000001, 10000000, true) == 10000001);
static_assert(qpc_ticks_100ns(10, 3, false) == 33333333);
static_assert(qpc_ticks_100ns(10, 3, true) == 33333334);
static_assert(qpc_ticks_100ns(INT64_MAX, 1000000000, false) == 92233720368547758);
static_assert(qpc_ticks_100ns(INT64_MAX, 1000000000, true) == 92233720368547759);
int64_t qpc_100ns(bool round_up = false, ClockDiagnostic* clock = nullptr) {
    LARGE_INTEGER counter{}, frequency{};
    require(QueryPerformanceCounter(&counter) && QueryPerformanceFrequency(&frequency) &&
            counter.QuadPart > 0 && frequency.QuadPart > 0 && frequency.QuadPart <= 1000000000,
            failed, "qpc-clock");
    auto whole = counter.QuadPart / frequency.QuadPart;
    require(whole < INT64_MAX / 10000000 - 1, failed, "qpc-clock");
    auto now = qpc_ticks_100ns(counter.QuadPart, frequency.QuadPart, round_up);
    if (clock) {
        clock->qpc_counter = counter.QuadPart;
        clock->qpc_frequency = frequency.QuadPart;
        clock->observed_now_100ns = now;
    }
    return now;
}
void write_all(void const* data, DWORD size) {
    auto output = GetStdHandle(STD_OUTPUT_HANDLE);
    auto bytes = static_cast<uint8_t const*>(data);
    while (size) {
        DWORD written = 0;
        require(WriteFile(output, bytes, size, &written, nullptr) && written, failed, "pipe-write");
        bytes += written; size -= written;
    }
}
void validate_request(Request const& request, Input const& p, uint64_t last_id) {
    require(std::memcmp(request.magic, "VGASREQ2", 8) == 0 && request.size == sizeof(Request) &&
            (request.opcode == 1 || request.opcode == 2) && request.id > last_id &&
            request.generation == p.generation && request.reserved == 0 &&
            request.wait_ms >= 50 && request.wait_ms <= 1200, failed, "request-protocol");
    if (request.opcode == 2) {
        require(request.left == 0 && request.top == 0 && request.width == 0 && request.height == 0,
                failed, "request-protocol");
    } else {
        require(request.width >= 16 && request.height >= 16 &&
                roi_inside(request.left, request.top, request.width, request.height, p.width, p.height),
                stale, "request-roi");
    }
}
void pin_graphics_capture_module() {
    // Experimental module-lifetime test, not a proven crash-cause diagnosis.
    // Keep only the already-loaded system WGC module mapped through apartment
    // teardown and process return. Every object release/Close and RoUninitialize
    // below still runs unchanged. PIN lasts until process termination.
    // https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulehandleexw
    wchar_t directory[MAX_PATH]{};
    UINT length = GetSystemDirectoryW(directory, MAX_PATH);
    require(length > 0 && length < MAX_PATH && directory[length] == L'\0',
            failed, "capture-module-pin");
    std::wstring path(directory, length);
    require(path.find(L'\0') == std::wstring::npos, failed, "capture-module-pin");
    if (path.back() != L'\\') path += L'\\';
    path += L"GraphicsCapture.dll";
    HMODULE module = nullptr;
    // A full system path avoids basename ambiguity. This API cannot load a
    // missing module, and failure has no DLL-search or LoadLibrary fallback.
    require(GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN, path.c_str(), &module) &&
            module != nullptr, failed, "capture-module-pin");
}
void run(Input const& p) {
    phase("support");
    require(ApiInformation::IsApiContractPresent(L"Windows.Foundation.UniversalApiContract", 8) &&
            GraphicsCaptureSession::IsSupported(), unsupported, "capture-supported");
    phase("validate-initial");
    auto geometry = validate(p);
    phase("device");
    com_ptr<ID3D11Device> device;
    com_ptr<ID3D11DeviceContext> context;
    D3D_FEATURE_LEVEL level{};
    HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION, device.put(), &level, context.put());
    // WARP is an ordinary OS renderer, useful on remote/CI desktops. It does not
    // change the capture target or permission and is not a screen fallback.
    if (FAILED(hr)) {
        device = nullptr; context = nullptr;
        hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_WARP, nullptr,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT, nullptr, 0, D3D11_SDK_VERSION, device.put(), &level, context.put());
    }
    check_hresult(hr);
    auto dxgi = device.as<IDXGIDevice>();
    com_ptr<IInspectable> inspectable;
    check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi.get(), inspectable.put()));
    auto runtime_device = inspectable.as<IDirect3DDevice>();
    phase("item-create");
    auto factory = get_activation_factory<GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
    GraphicsCaptureItem item{nullptr};
    check_hresult(factory->CreateForWindow(p.hwnd, guid_of<GraphicsCaptureItem>(), put_abi(item)));
    auto size = item.Size();
    phase("item-size");
    dimensions(0, 0, size.Width, size.Height, 0, 0,
               int64_t(geometry.frame.right) - geometry.frame.left, int64_t(geometry.frame.bottom) - geometry.frame.top);
    int model = capture_model(geometry.window, geometry.frame, size.Width, size.Height);
    require(model != 0, stale, "item-dimensions");
    require(model != -1, stale, "capture-origin");
    // Item extent constrains the GPU allocation; actual frame ContentSize below
    // independently selects exactly one original, still-validated rectangle.
    // Microsoft's pool contract leaves padding outside smaller content undefined:
    // https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture
    // That padding is never included in the staged client ROI.
    phase("session-create");
    auto pool = Direct3D11CaptureFramePool::CreateFreeThreaded(runtime_device,
        DirectXPixelFormat::B8G8R8A8UIntNormalized, 1, size);
    auto session = pool.CreateCaptureSession(item);
    // Factory, item, pool and session are alive; capture has not started.
    pin_graphics_capture_module();
    if (ApiInformation::IsPropertyPresent(L"Windows.Graphics.Capture.GraphicsCaptureSession", L"IsCursorCaptureEnabled"))
        session.IsCursorCaptureEnabled(false);
    // Secondary windows default to false on platforms before this API exists.
    if (ApiInformation::IsPropertyPresent(L"Windows.Graphics.Capture.GraphicsCaptureSession", L"IncludeSecondaryWindows"))
        session.IncludeSecondaryWindows(false);
    // Leave Windows' normal visible capture border enabled. Never request borderless access.
    auto signal = std::make_shared<CaptureSignal>();
    require(signal->event.value != nullptr, failed);
    auto arrived = pool.FrameArrived([signal](auto const&, auto const&) { SetEvent(signal->event.value); });
    auto closed = item.Closed([signal](auto const&, auto const&) {
        signal->closed.store(true); SetEvent(signal->event.value);
    });
    phase("session-start");
    session.StartCapture();
    uint64_t last_id = 0;
    int64_t last_frame_time = 0;
    auto lease = GetTickCount64() + idle_lease_ms;
    while (true) {
        phase("validate-idle");
        require(!signal->closed.load(), stale, "item-open");
        validate(p, &geometry, true);
        require(GetTickCount64() < lease, timed_out, "idle-lease");
        DWORD available = 0;
        if (!PeekNamedPipe(GetStdHandle(STD_INPUT_HANDLE), nullptr, 0, nullptr, &available, nullptr)) {
            require(GetLastError() == ERROR_BROKEN_PIPE, failed, "pipe-read");
            break; // EOF closes the GPU session without any readback.
        }
        if (available < sizeof(Request)) { Sleep(watchdog_ms); continue; }
        // Only one request may be outstanding. Reject pipelined commands/bytes.
        require(available == sizeof(Request), failed, "request-protocol");
        Request request{}; DWORD count = 0;
        require(ReadFile(GetStdHandle(STD_INPUT_HANDLE), &request, sizeof(request), &count, nullptr) &&
                count == sizeof(request), failed, "pipe-read");
        validate_request(request, p, last_id);
        last_id = request.id;
        if (request.opcode == 2) break;
        lease = GetTickCount64() + idle_lease_ms; // Renew only a validated request.
        int64_t cutoff = qpc_100ns(true);
        int64_t previous_frame_time = last_frame_time;
        auto deadline = GetTickCount64() + request.wait_ms;
        Direct3D11CaptureFrame frame{nullptr};
        RECT capture_bounds{};
        int64_t frame_time = 0;
        bool frame_ready = false;
        while (GetTickCount64() < deadline) {
            phase("validate-frame-wait");
            require(!signal->closed.load(), stale, "item-open");
            validate(p, &geometry); // STRICT, including our overlay.
            phase("frame-wait");
            if (!frame) frame = pool.TryGetNextFrame();
            if (frame) {
                frame_time = frame.SystemRelativeTime().count();
                frame_clock(cutoff, frame_time, previous_frame_time);
                require(frame_time > 0, stale, "frame-timestamp");
                bool timestamp_ready = frame_time <= qpc_100ns(false, &diagnostic.clock);
                auto candidate = frame.ContentSize();
                int selected = content_model(geometry.window, geometry.frame, size.Width, size.Height,
                                             candidate.Width, candidate.Height);
                require(selected != -1, stale, "capture-origin");
                require(selected != -2, stale, "content-in-pool");
                // Drop every pre-request/previous frame. No queued pixels can
                // become a successful response merely because ROI is unchanged.
                if (selected > 0 && frame_time > cutoff && frame_time > last_frame_time) {
                    if (timestamp_ready) {
                        capture_bounds = selected == 1 ? geometry.window : geometry.frame;
                        frame_ready = true;
                        break;
                    }
                    // Retain at most this GPU frame until its unchanged strict
                    // timestamp bound holds. Revalidate all guards each cycle;
                    // never copy/map it or renew the original request deadline.
                } else {
                    frame.Close(); frame = nullptr;
                }
            }
            auto now = GetTickCount64();
            if (now >= deadline) break;
            WaitForSingleObject(signal->event.value, DWORD(std::min<uint64_t>(watchdog_ms, deadline - now)));
        }
        require(frame_ready && GetTickCount64() < deadline, timed_out, "frame-deadline");
        phase("frame-size");
        auto content = frame.ContentSize();
        // Bind the one selected content origin for this frame. All original window,
        // DWM and client geometry is still checked before and after the pixel copy.
        int64_t content_width = int64_t(capture_bounds.right) - capture_bounds.left;
        int64_t content_height = int64_t(capture_bounds.bottom) - capture_bounds.top;
        dimensions(0, 0, content.Width, content.Height, 0, 0, content_width, content_height);
        require(content.Width == content_width && content.Height == content_height, stale, "frame-dimensions");
        phase("texture");
        auto access = frame.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
        com_ptr<ID3D11Texture2D> texture;
        check_hresult(access->GetInterface(guid_of<ID3D11Texture2D>(), texture.put_void()));
        D3D11_TEXTURE2D_DESC source{};
        texture->GetDesc(&source);
        dimensions(0, 0, source.Width, source.Height, 0, 0, size.Width, size.Height);
        require(source.Width == UINT(size.Width) && source.Height == UINT(size.Height) &&
                source.Format == DXGI_FORMAT_B8G8R8A8_UNORM && source.SampleDesc.Count == 1, stale, "texture-layout");
        UINT left = UINT(int64_t(p.x) - capture_bounds.left + request.left);
        UINT top = UINT(int64_t(p.y) - capture_bounds.top + request.top);
        require(roi_inside(left, top, request.width, request.height, content.Width, content.Height), stale, "content-roi");
        require(roi_inside(left, top, request.width, request.height, source.Width, source.Height), stale, "texture-roi");
        phase("validate-before-copy");
        validate(p, &geometry);
        require(!signal->closed.load(), stale, "item-open");
        phase("staging-copy");
        D3D11_TEXTURE2D_DESC output{};
        output.Width = request.width; output.Height = request.height;
        output.MipLevels = output.ArraySize = 1; output.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        output.SampleDesc.Count = 1; output.Usage = D3D11_USAGE_STAGING;
        output.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        com_ptr<ID3D11Texture2D> staging;
        check_hresult(device->CreateTexture2D(&output, nullptr, staging.put()));
        D3D11_BOX box{left, top, 0, left + UINT(request.width), top + UINT(request.height), 1};
        context->CopySubresourceRegion(staging.get(), 0, 0, 0, 0, texture.get(), 0, &box);
        context->Flush();
        phase("map");
        D3D11_MAPPED_SUBRESOURCE mapped{};
        hr = DXGI_ERROR_WAS_STILL_DRAWING;
        while (hr == DXGI_ERROR_WAS_STILL_DRAWING && GetTickCount64() < deadline) {
            hr = context->Map(staging.get(), 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &mapped);
            if (hr == DXGI_ERROR_WAS_STILL_DRAWING) {
                validate(p, &geometry);
                require(!signal->closed.load(), stale, "item-open");
                Sleep(2);
            }
        }
        require(hr != DXGI_ERROR_WAS_STILL_DRAWING, timed_out, "map-deadline");
        check_hresult(hr);
        SensitivePixels pixels;
        try {
            phase("validate-after-map");
            validate(p, &geometry);
            require(!signal->closed.load(), stale, "item-open");
            phase("copy-out");
            require(mapped.pData && mapped.RowPitch >= UINT(request.width) * 4, failed, "mapped-layout");
            pixels.resize(size_t(request.width) * request.height * 4);
            for (int row = 0; row < request.height; ++row)
                std::memcpy(pixels.data() + size_t(row) * request.width * 4,
                    static_cast<uint8_t*>(mapped.pData) + size_t(row) * mapped.RowPitch, size_t(request.width) * 4);
        } catch (...) { context->Unmap(staging.get(), 0); throw; }
        context->Unmap(staging.get(), 0);
        phase("validate-final");
        validate(p, &geometry); // STRICT after CPU copy, before any output.
        require(!signal->closed.load(), stale, "item-open");
        frame.Close(); frame = nullptr;
        texture = nullptr; staging = nullptr;
        last_frame_time = frame_time;
        Response response{{'V','G','A','S','R','S','P','2'}, 0, 1, request.id, p.generation,
            uint32_t(request.width), uint32_t(request.height), uint32_t(pixels.size()), 0, cutoff, frame_time};
        phase("write-output");
        write_all(&response, sizeof(response));
        write_all(pixels.data(), DWORD(pixels.size()));
        SecureZeroMemory(pixels.data(), pixels.size()); pixels.clear();
        phase("validate-final");
        validate(p, &geometry); // Still strict until all ROI bytes have left us.
        require(!signal->closed.load(), stale, "item-open");
        phase("validate-idle");
        validate(p, &geometry, true);
        frame_clock(cutoff, frame_time, previous_frame_time);
        Idle idle{{'V','G','A','S','I','D','L','2'}, request.id, p.generation, qpc_100ns(false, &diagnostic.clock)};
        require(idle.entered >= frame_time, stale, "frame-timestamp");
        // Parent exposes nothing until this matching guarded-idle trailer arrives.
        write_all(&idle, sizeof(idle));
    }
    phase("shutdown");
    shutdown_checkpoint(ShutdownStage::frame_arrived_revoke);
    pool.FrameArrived(arrived);
    shutdown_checkpoint(ShutdownStage::item_closed_revoke);
    item.Closed(closed);
    shutdown_checkpoint(ShutdownStage::session_close);
    session.Close();
    shutdown_checkpoint(ShutdownStage::pool_close);
    pool.Close();
    shutdown_checkpoint(ShutdownStage::local_release);
    // Native driver Close can block. Parent Job kill/request deadline is separate
    // from this thread. The 25 ms schedule is NOT a 50 ms teardown guarantee.
}
}

int wmain(int argc, wchar_t** argv) {
    try {
        auto p = parse(argc, argv);
        char start = 0; DWORD read = 0;
        require(ReadFile(GetStdHandle(STD_INPUT_HANDLE), &start, 1, &read, nullptr) &&
                read == 1 && start == 'C', failed, "start-gate");
        // This is the only held process handle, metadata + lifetime wait only.
        Handle parent(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, p.parent_pid));
        p.parent = parent.value;
        validate_parent(p);
        require(SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) ||
            AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2), failed, "dpi-context");
        init_apartment(apartment_type::multi_threaded);
        run(p);
        shutdown_checkpoint(ShutdownStage::apartment_uninit);
        uninit_apartment();
        shutdown_checkpoint(ShutdownStage::process_return);
        return 0;
    } catch (Failure const& error) { report_failure(error.code, error.check); return error.code; }
      catch (hresult_error const& error) {
        int code = error.code() == E_ACCESSDENIED ? protected_content : failed;
        report_failure(code, "hresult", uint32_t(error.code())); return code;
      } catch (...) { report_failure(failed, "exception"); return failed; }
}
