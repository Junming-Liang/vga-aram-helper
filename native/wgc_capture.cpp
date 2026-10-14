// VGA's original HWND-only, single-frame Windows Graphics Capture helper.
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
// Failure-only metadata protocol on stderr. All strings are static IDs, all
// values are numeric dimensions/styles; never titles, paths, IDs or pixels.
// stdout remains exclusively the exact ROI pixel protocol on successful capture.
struct Diagnostic {
    char const* phase = "startup";
    int64_t observed[4]{}, expected[4]{}, window_rect[4]{}, frame_rect[4]{};
    uint32_t style = 0, extended_style = 0;
} diagnostic;
void phase(char const* value) {
    diagnostic.phase = value;
    std::fill_n(diagnostic.observed, 4, int64_t(0));
    std::fill_n(diagnostic.expected, 4, int64_t(0));
    diagnostic.style = diagnostic.extended_style = 0;
}
void dimensions(int64_t x, int64_t y, int64_t width, int64_t height,
                int64_t ex = 0, int64_t ey = 0, int64_t ew = 0, int64_t eh = 0) {
    diagnostic.observed[0] = x; diagnostic.observed[1] = y;
    diagnostic.observed[2] = width; diagnostic.observed[3] = height;
    diagnostic.expected[0] = ex; diagnostic.expected[1] = ey;
    diagnostic.expected[2] = ew; diagnostic.expected[3] = eh;
}
struct Failure { int code; char const* check; };
void require(bool value, int code = stale, char const* check = "invariant") {
    if (!value) throw Failure{code, check};
}
void report_failure(int code, char const* check, uint32_t hresult = 0) noexcept {
    // One bounded write, no logging dependency, no exception text or system data.
    // The parent drains this pipe concurrently within the same process deadline.
    char data[1024]{};
    int count = std::snprintf(data, sizeof(data),
        "{\"schema_version\":1,\"code\":%d,\"phase\":\"%s\",\"check\":\"%s\","
        "\"hresult\":%u,\"observed\":[%lld,%lld,%lld,%lld],"
        "\"expected\":[%lld,%lld,%lld,%lld],\"window_rect\":[%lld,%lld,%lld,%lld],"
        "\"frame_rect\":[%lld,%lld,%lld,%lld],\"style\":%u,\"extended_style\":%u}\n",
        code, diagnostic.phase, check, static_cast<unsigned int>(hresult),
        static_cast<long long>(diagnostic.observed[0]), static_cast<long long>(diagnostic.observed[1]),
        static_cast<long long>(diagnostic.observed[2]), static_cast<long long>(diagnostic.observed[3]),
        static_cast<long long>(diagnostic.expected[0]), static_cast<long long>(diagnostic.expected[1]),
        static_cast<long long>(diagnostic.expected[2]), static_cast<long long>(diagnostic.expected[3]),
        static_cast<long long>(diagnostic.window_rect[0]), static_cast<long long>(diagnostic.window_rect[1]),
        static_cast<long long>(diagnostic.window_rect[2]), static_cast<long long>(diagnostic.window_rect[3]),
        static_cast<long long>(diagnostic.frame_rect[0]), static_cast<long long>(diagnostic.frame_rect[1]),
        static_cast<long long>(diagnostic.frame_rect[2]), static_cast<long long>(diagnostic.frame_rect[3]),
        static_cast<unsigned int>(diagnostic.style), static_cast<unsigned int>(diagnostic.extended_style));
    if (count > 0 && count < int(sizeof(data))) {
        DWORD written = 0;
        WriteFile(GetStdHandle(STD_ERROR_HANDLE), data, DWORD(count), &written, nullptr);
    }
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
struct Input {
    HWND hwnd;
    DWORD pid;
    uint64_t created;
    int x, y, width, height, left, top, roi_width, roi_height;
    DWORD timeout;
};
struct Geometry { RECT frame; POINT origin; RECT client; };
bool same(RECT const& a, RECT const& b) {
    return a.left == b.left && a.top == b.top && a.right == b.right && a.bottom == b.bottom;
}
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
    require(argc == 14 && std::wstring(argv[1]) == L"--capture-v1", failed);
    int64_t n[12];
    for (int i = 0; i < 12; ++i) n[i] = number(argv[i + 2]);
    require(n[0] > 0 && n[1] > 0 && n[1] <= UINT32_MAX && n[2] > 0, failed);
    for (int i = 3; i <= 10; ++i)
        require(n[i] >= INT32_MIN && n[i] <= INT32_MAX, failed);
    require(n[5] >= 64 && n[6] >= 64 && uint64_t(n[5]) * n[6] <= pixel_budget, failed);
    require(n[7] >= 0 && n[8] >= 0 && n[9] >= 16 && n[10] >= 16 &&
            n[7] + n[9] <= n[5] && n[8] + n[10] <= n[6], failed);
    require(n[3] + n[5] <= INT32_MAX && n[4] + n[6] <= INT32_MAX, failed);
    require(n[11] >= 50 && n[11] <= 1200, failed);
    return {reinterpret_cast<HWND>(n[0]), static_cast<DWORD>(n[1]), uint64_t(n[2]),
            int(n[3]), int(n[4]), int(n[5]), int(n[6]), int(n[7]), int(n[8]),
            int(n[9]), int(n[10]), DWORD(n[11])};
}
uint64_t creation_time(DWORD pid) {
    // Metadata only. Never request VM_READ, VM_WRITE or PROCESS_ALL_ACCESS.
    Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid));
    require(process.value != nullptr, stale, "process-open");
    FILETIME created{}, exited{}, kernel{}, user{};
    require(GetProcessTimes(process.value, &created, &exited, &kernel, &user) != FALSE, stale, "process-times");
    return (uint64_t(created.dwHighDateTime) << 32) | created.dwLowDateTime;
}
struct ZOrder { HWND target; RECT client; bool found = false, blocked = false, unreadable = false; };
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
        dimensions(other.left, other.top, int64_t(other.right) - other.left,
                   int64_t(other.bottom) - other.top, scope.client.left, scope.client.top,
                   int64_t(scope.client.right) - scope.client.left, int64_t(scope.client.bottom) - scope.client.top);
        diagnostic.style = uint32_t(GetWindowLongPtrW(hwnd, GWL_STYLE));
        diagnostic.extended_style = uint32_t(GetWindowLongPtrW(hwnd, GWL_EXSTYLE));
        scope.blocked = true; return FALSE;
    }
    return TRUE;
}
Geometry validate(Input const& p, Geometry const* expected = nullptr) {
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
    RECT window{};
    if (GetWindowRect(p.hwnd, &window)) {
        diagnostic.window_rect[0] = window.left; diagnostic.window_rect[1] = window.top;
        diagnostic.window_rect[2] = int64_t(window.right) - window.left;
        diagnostic.window_rect[3] = int64_t(window.bottom) - window.top;
    }
    dimensions(g.frame.left, g.frame.top, fw, fh, p.x, p.y, p.width, p.height);
    require(fw > 0 && fh > 0 && fw * fh <= pixel_budget, stale, "frame-budget");
    require(p.x >= g.frame.left && p.y >= g.frame.top &&
            int64_t(p.x) + p.width <= g.frame.right && int64_t(p.y) + p.height <= g.frame.bottom, stale, "client-in-frame");
    if (expected) require(same(g.frame, expected->frame) && same(g.client, expected->client) &&
                          g.origin.x == expected->origin.x && g.origin.y == expected->origin.y, stale, "geometry-stable");
    RECT bounds{p.x, p.y, p.x + p.width, p.y + p.height};
    MONITORINFO monitor{sizeof(monitor)};
    auto selected = MonitorFromRect(&bounds, MONITOR_DEFAULTTONULL);
    require(selected && GetMonitorInfoW(selected, &monitor) &&
            monitor.rcMonitor.left <= bounds.left && monitor.rcMonitor.top <= bounds.top &&
            bounds.right <= monitor.rcMonitor.right && bounds.bottom <= monitor.rcMonitor.bottom, stale, "client-on-monitor");
    ZOrder order{p.hwnd, bounds};
    EnumWindows(check_above, reinterpret_cast<LPARAM>(&order));
    require(!order.blocked, stale, order.unreadable ? "occluder-query" : "occluder-overlap");
    require(order.found, stale, "zorder-target");
    return g;
}
std::vector<uint8_t> capture(Input const& p) {
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
    require(size.Width == geometry.frame.right - geometry.frame.left &&
            size.Height == geometry.frame.bottom - geometry.frame.top, stale, "item-dimensions");
    phase("session-create");
    auto pool = Direct3D11CaptureFramePool::CreateFreeThreaded(runtime_device,
        DirectXPixelFormat::B8G8R8A8UIntNormalized, 1, size);
    auto session = pool.CreateCaptureSession(item);
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
    auto deadline = GetTickCount64() + p.timeout;
    Direct3D11CaptureFrame frame{nullptr};
    while (GetTickCount64() < deadline) {
        phase("validate-frame-wait");
        require(!signal->closed.load(), stale, "item-open");
        validate(p, &geometry);
        phase("frame-wait");
        frame = pool.TryGetNextFrame();
        if (frame) {
            auto candidate_size = frame.ContentSize();
            if (candidate_size.Width == size.Width && candidate_size.Height == size.Height) break;
            // Some Windows versions initially deliver a differently-sized frame.
            // No pixels are mapped from it; keep waiting only while original
            // window geometry remains exact and this one deadline has time left.
            frame.Close(); frame = nullptr;
        }
        WaitForSingleObject(signal->event.value, 10);
    }
    require(bool(frame), timed_out, "frame-deadline");
    phase("frame-size");
    auto content = frame.ContentSize();
    // Resizes are rejected rather than reusing an old surface with undefined
    // pixels. The next request creates a fresh pool from freshly proved geometry.
    dimensions(0, 0, content.Width, content.Height, 0, 0, size.Width, size.Height);
    require(content.Width == size.Width && content.Height == size.Height, stale, "frame-dimensions");
    phase("texture");
    auto access = frame.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
    com_ptr<ID3D11Texture2D> texture;
    check_hresult(access->GetInterface(guid_of<ID3D11Texture2D>(), texture.put_void()));
    D3D11_TEXTURE2D_DESC source{};
    texture->GetDesc(&source);
    dimensions(0, 0, source.Width, source.Height, 0, 0, size.Width, size.Height);
    require(source.Width == UINT(size.Width) && source.Height == UINT(size.Height) &&
            source.Format == DXGI_FORMAT_B8G8R8A8_UNORM && source.SampleDesc.Count == 1, stale, "texture-layout");
    UINT left = UINT(p.x - geometry.frame.left + p.left), top = UINT(p.y - geometry.frame.top + p.top);
    require(uint64_t(left) + p.roi_width <= source.Width && uint64_t(top) + p.roi_height <= source.Height, stale, "texture-roi");
    phase("validate-before-copy");
    validate(p, &geometry);
    require(!signal->closed.load(), stale, "item-open");
    phase("staging-copy");
    D3D11_TEXTURE2D_DESC output{};
    output.Width = p.roi_width; output.Height = p.roi_height;
    output.MipLevels = output.ArraySize = 1; output.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    output.SampleDesc.Count = 1; output.Usage = D3D11_USAGE_STAGING;
    output.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    com_ptr<ID3D11Texture2D> staging;
    check_hresult(device->CreateTexture2D(&output, nullptr, staging.put()));
    D3D11_BOX box{left, top, 0, left + UINT(p.roi_width), top + UINT(p.roi_height), 1};
    context->CopySubresourceRegion(staging.get(), 0, 0, 0, 0, texture.get(), 0, &box);
    context->Flush();
    phase("map");
    D3D11_MAPPED_SUBRESOURCE mapped{};
    hr = DXGI_ERROR_WAS_STILL_DRAWING;
    while (hr == DXGI_ERROR_WAS_STILL_DRAWING && GetTickCount64() < deadline) {
        hr = context->Map(staging.get(), 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &mapped);
        if (hr == DXGI_ERROR_WAS_STILL_DRAWING) Sleep(2);
    }
    require(hr != DXGI_ERROR_WAS_STILL_DRAWING, timed_out, "map-deadline");
    check_hresult(hr);
    std::vector<uint8_t> pixels;
    try {
        phase("validate-after-map");
        validate(p, &geometry);
        require(!signal->closed.load(), stale, "item-open");
        phase("copy-out");
        require(mapped.pData && mapped.RowPitch >= UINT(p.roi_width) * 4, failed, "mapped-layout");
        pixels.resize(size_t(p.roi_width) * p.roi_height * 4);
        for (int row = 0; row < p.roi_height; ++row)
            std::memcpy(pixels.data() + size_t(row) * p.roi_width * 4,
                static_cast<uint8_t*>(mapped.pData) + size_t(row) * mapped.RowPitch, size_t(p.roi_width) * 4);
    } catch (...) { context->Unmap(staging.get(), 0); throw; }
    context->Unmap(staging.get(), 0);
    phase("shutdown");
    frame.Close();
    pool.FrameArrived(arrived);
    session.Close();
    pool.Close();
    phase("validate-final");
    validate(p, &geometry);
    require(!signal->closed.load(), stale, "item-open");
    item.Closed(closed);
    return pixels;
}
void write_all(void const* data, DWORD size) {
    auto output = GetStdHandle(STD_OUTPUT_HANDLE);
    auto bytes = static_cast<uint8_t const*>(data);
    while (size) {
        DWORD written = 0;
        require(WriteFile(output, bytes, size, &written, nullptr) && written, failed);
        bytes += written; size -= written;
    }
}
}

int wmain(int argc, wchar_t** argv) {
    try {
        auto p = parse(argc, argv);
        // Parent first assigns this exact child to its non-inheritable,
        // kill-on-close Job, then releases this pipe gate. Parent death before
        // assignment yields EOF; after assignment the Job terminates us.
        char start = 0; DWORD read = 0;
        require(ReadFile(GetStdHandle(STD_INPUT_HANDLE), &start, 1, &read, nullptr) &&
                read == 1 && start == 'C', failed, "start-gate");
        // Process-local coordinate mode only. Does not modify system settings.
        require(SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) ||
            AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2), failed, "dpi-context");
        init_apartment(apartment_type::multi_threaded);
        auto pixels = capture(p);
        phase("write-output");
        char magic[8] = {'V','G','A','W','G','C','1','\0'};
        uint32_t header[4] = {1, uint32_t(p.roi_width), uint32_t(p.roi_height), uint32_t(pixels.size())};
        write_all(magic, sizeof(magic)); write_all(header, sizeof(header));
        write_all(pixels.data(), DWORD(pixels.size()));
        uninit_apartment();
        return 0;
    } catch (Failure const& error) { report_failure(error.code, error.check); return error.code; }
      catch (hresult_error const& error) {
        int code = error.code() == E_ACCESSDENIED ? protected_content : failed;
        report_failure(code, "hresult", uint32_t(error.code())); return code;
      } catch (...) { report_failure(failed, "exception"); return failed; }
}
