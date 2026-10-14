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
struct Failure { int code; };
void require(bool value, int code = stale) { if (!value) throw Failure{code}; }
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
    require(process.value != nullptr);
    FILETIME created{}, exited{}, kernel{}, user{};
    require(GetProcessTimes(process.value, &created, &exited, &kernel, &user) != FALSE);
    return (uint64_t(created.dwHighDateTime) << 32) | created.dwLowDateTime;
}
struct ZOrder { HWND target; RECT client; bool found = false, blocked = false; };
BOOL CALLBACK check_above(HWND hwnd, LPARAM pointer) {
    auto& scope = *reinterpret_cast<ZOrder*>(pointer);
    if (hwnd == scope.target) { scope.found = true; return FALSE; }
    if (!IsWindowVisible(hwnd) || IsIconic(hwnd)) return TRUE;
    DWORD cloaked = 0;
    if (SUCCEEDED(DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, &cloaked, sizeof(cloaked))) && cloaked)
        return TRUE;
    RECT other{};
    if (!GetWindowRect(hwnd, &other) || intersects(scope.client, other)) {
        scope.blocked = true; return FALSE;
    }
    return TRUE;
}
Geometry validate(Input const& p, Geometry const* expected = nullptr) {
    require(IsWindow(p.hwnd) && IsWindowVisible(p.hwnd) && !IsIconic(p.hwnd));
    require(GetAncestor(p.hwnd, GA_ROOT) == p.hwnd &&
            GetAncestor(GetForegroundWindow(), GA_ROOT) == p.hwnd);
    DWORD pid = 0;
    require(GetWindowThreadProcessId(p.hwnd, &pid) != 0 && pid == p.pid);
    require(creation_time(pid) == p.created);
    DWORD cloaked = 0, affinity = 0;
    require(SUCCEEDED(DwmGetWindowAttribute(p.hwnd, DWMWA_CLOAKED, &cloaked, sizeof(cloaked))) && !cloaked);
    // This query is not available for every window style. A known protection
    // is always denied; WGC denial/blank output is never retried through GDI.
    if (GetWindowDisplayAffinity(p.hwnd, &affinity)) require(!affinity, protected_content);
    Geometry g{};
    require(GetClientRect(p.hwnd, &g.client) && ClientToScreen(p.hwnd, &g.origin));
    require(g.client.left == 0 && g.client.top == 0 && g.client.right == p.width &&
            g.client.bottom == p.height && g.origin.x == p.x && g.origin.y == p.y);
    require(SUCCEEDED(DwmGetWindowAttribute(p.hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, &g.frame, sizeof(g.frame))));
    int64_t fw = int64_t(g.frame.right) - g.frame.left, fh = int64_t(g.frame.bottom) - g.frame.top;
    require(fw > 0 && fh > 0 && fw * fh <= pixel_budget);
    require(p.x >= g.frame.left && p.y >= g.frame.top &&
            int64_t(p.x) + p.width <= g.frame.right && int64_t(p.y) + p.height <= g.frame.bottom);
    if (expected) require(same(g.frame, expected->frame) && same(g.client, expected->client) &&
                          g.origin.x == expected->origin.x && g.origin.y == expected->origin.y);
    RECT bounds{p.x, p.y, p.x + p.width, p.y + p.height};
    MONITORINFO monitor{sizeof(monitor)};
    auto selected = MonitorFromRect(&bounds, MONITOR_DEFAULTTONULL);
    require(selected && GetMonitorInfoW(selected, &monitor) &&
            monitor.rcMonitor.left <= bounds.left && monitor.rcMonitor.top <= bounds.top &&
            bounds.right <= monitor.rcMonitor.right && bounds.bottom <= monitor.rcMonitor.bottom);
    ZOrder order{p.hwnd, bounds};
    EnumWindows(check_above, reinterpret_cast<LPARAM>(&order));
    require(order.found && !order.blocked);
    return g;
}
std::vector<uint8_t> capture(Input const& p) {
    require(ApiInformation::IsApiContractPresent(L"Windows.Foundation.UniversalApiContract", 8) &&
            GraphicsCaptureSession::IsSupported(), unsupported);
    auto geometry = validate(p);
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
    auto factory = get_activation_factory<GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
    GraphicsCaptureItem item{nullptr};
    check_hresult(factory->CreateForWindow(p.hwnd, guid_of<GraphicsCaptureItem>(), put_abi(item)));
    auto size = item.Size();
    require(size.Width == geometry.frame.right - geometry.frame.left &&
            size.Height == geometry.frame.bottom - geometry.frame.top);
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
    session.StartCapture();
    auto deadline = GetTickCount64() + p.timeout;
    Direct3D11CaptureFrame frame{nullptr};
    while (GetTickCount64() < deadline) {
        require(!signal->closed.load());
        validate(p, &geometry);
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
    require(bool(frame), timed_out);
    auto content = frame.ContentSize();
    // Resizes are rejected rather than reusing an old surface with undefined
    // pixels. The next request creates a fresh pool from freshly proved geometry.
    require(content.Width == size.Width && content.Height == size.Height);
    auto access = frame.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
    com_ptr<ID3D11Texture2D> texture;
    check_hresult(access->GetInterface(guid_of<ID3D11Texture2D>(), texture.put_void()));
    D3D11_TEXTURE2D_DESC source{};
    texture->GetDesc(&source);
    require(source.Width == UINT(size.Width) && source.Height == UINT(size.Height) &&
            source.Format == DXGI_FORMAT_B8G8R8A8_UNORM && source.SampleDesc.Count == 1);
    UINT left = UINT(p.x - geometry.frame.left + p.left), top = UINT(p.y - geometry.frame.top + p.top);
    require(uint64_t(left) + p.roi_width <= source.Width && uint64_t(top) + p.roi_height <= source.Height);
    validate(p, &geometry);
    require(!signal->closed.load());
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
    D3D11_MAPPED_SUBRESOURCE mapped{};
    hr = DXGI_ERROR_WAS_STILL_DRAWING;
    while (hr == DXGI_ERROR_WAS_STILL_DRAWING && GetTickCount64() < deadline) {
        hr = context->Map(staging.get(), 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &mapped);
        if (hr == DXGI_ERROR_WAS_STILL_DRAWING) Sleep(2);
    }
    require(hr != DXGI_ERROR_WAS_STILL_DRAWING, timed_out);
    check_hresult(hr);
    std::vector<uint8_t> pixels;
    try {
        validate(p, &geometry);
        require(!signal->closed.load());
        require(mapped.pData && mapped.RowPitch >= UINT(p.roi_width) * 4, failed);
        pixels.resize(size_t(p.roi_width) * p.roi_height * 4);
        for (int row = 0; row < p.roi_height; ++row)
            std::memcpy(pixels.data() + size_t(row) * p.roi_width * 4,
                static_cast<uint8_t*>(mapped.pData) + size_t(row) * mapped.RowPitch, size_t(p.roi_width) * 4);
    } catch (...) { context->Unmap(staging.get(), 0); throw; }
    context->Unmap(staging.get(), 0);
    frame.Close();
    pool.FrameArrived(arrived);
    session.Close();
    pool.Close();
    validate(p, &geometry);
    require(!signal->closed.load());
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
                read == 1 && start == 'C', failed);
        // Process-local coordinate mode only. Does not modify system settings.
        require(SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) ||
            AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2), failed);
        init_apartment(apartment_type::multi_threaded);
        auto pixels = capture(p);
        char magic[8] = {'V','G','A','W','G','C','1','\0'};
        uint32_t header[4] = {1, uint32_t(p.roi_width), uint32_t(p.roi_height), uint32_t(pixels.size())};
        write_all(magic, sizeof(magic)); write_all(header, sizeof(header));
        write_all(pixels.data(), DWORD(pixels.size()));
        uninit_apartment();
        return 0;
    } catch (Failure const& error) { return error.code; }
      catch (hresult_error const& error) {
        return error.code() == E_ACCESSDENIED ? protected_content : failed;
      } catch (...) { return failed; }
}
