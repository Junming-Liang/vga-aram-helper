// Original diagnostic fixture, not a League/Riot implementation or compatibility test.
// It paints only its supplied local PNG and can own one tiny diagnostic focus
// sink. It never opens another process, sends input, installs hooks, accesses the
// network, or changes OS settings.
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static class SessionWindowFixture
{
    private const uint WM_PAINT = 0x000F, WM_CLOSE = 0x0010, WM_DESTROY = 0x0002;
    private const uint WM_ERASEBKGND = 0x0014, WM_TIMER = 0x0113;
    // Test harness may request recreation of this process's own HWND only.
    private const uint WM_RECREATE_OWNED = 0x8000 + 73;
    // Zero-parameter commands accepted only by the activating CLIENT window.
    // OPEN returns the exact owned sink HWND after a foreground attempt; RETURN
    // returns 1 only after sink destruction and verified client foreground.
    // The harness independently verifies ownership, geometry, and foreground.
    private const uint WM_FOCUS_OWNED_SINK = 0x8000 + 74;
    private const uint WM_RETURN_OWNED_CLIENT = 0x8000 + 75;
    private const string FocusSinkClass = "VGAOwnedFocusSink";
    private const string FocusSinkTitle = "VGA owned focus sink";
    private static readonly WndProc WindowProcedure = Dispatch;
    private static readonly WndProc FocusSinkProcedure = DispatchFocusSink;
    private static Bitmap bitmap;
    private static string imagePath, readyPath, role, className;
    private static int x, y, width, height, lifetime, paintCount;
    private static bool recreating, noActivate;
    private static IntPtr window, focusSink;
    private static readonly Stopwatch Clock = new Stopwatch();

    [StructLayout(LayoutKind.Sequential)] private struct Point { public int x, y; }
    [StructLayout(LayoutKind.Sequential)] private struct Rect { public int left, top, right, bottom; }
    [StructLayout(LayoutKind.Sequential)] private struct Message
    {
        public IntPtr hwnd;
        public uint message;
        public UIntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public Point pt;
        public uint lPrivate;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct WindowClass
    {
        public uint cbSize, style;
        public WndProc lpfnWndProc;
        public int cbClsExtra, cbWndExtra;
        public IntPtr hInstance, hIcon, hCursor, hbrBackground;
        [MarshalAs(UnmanagedType.LPWStr)] public string lpszMenuName;
        [MarshalAs(UnmanagedType.LPWStr)] public string lpszClassName;
        public IntPtr hIconSm;
    }
    [StructLayout(LayoutKind.Sequential)] private struct Paint
    {
        public IntPtr hdc;
        public int fErase;
        public Rect rcPaint;
        public int fRestore, fIncUpdate;
        // Eight DWORDs preserve the native 32-byte inline reserved field.
        public uint reserved0, reserved1, reserved2, reserved3;
        public uint reserved4, reserved5, reserved6, reserved7;
    }
    [UnmanagedFunctionPointer(CallingConvention.Winapi)]
    private delegate IntPtr WndProc(IntPtr hwnd, uint message, UIntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern IntPtr GetModuleHandleW(string name);
    [DllImport("kernel32.dll", ExactSpelling = true)] private static extern uint GetCurrentProcessId();
    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern ushort RegisterClassExW(ref WindowClass wc);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern IntPtr CreateWindowExW(uint exStyle, string cls, string title, uint style,
        int x, int y, int width, int height, IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern IntPtr DefWindowProcW(IntPtr hwnd, uint message, UIntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    private static extern int GetMessageW(out Message message, IntPtr hwnd, uint min, uint max);
    [DllImport("user32.dll", ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool TranslateMessage(ref Message message);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern IntPtr DispatchMessageW(ref Message message);
    [DllImport("user32.dll", ExactSpelling = true)] private static extern void PostQuitMessage(int exitCode);
    [DllImport("user32.dll", ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool DestroyWindow(IntPtr hwnd);
    [DllImport("user32.dll", ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll", ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool UpdateWindow(IntPtr hwnd);
    [DllImport("user32.dll", ExactSpelling = true)] private static extern IntPtr BeginPaint(IntPtr hwnd, out Paint paint);
    [DllImport("user32.dll", ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool EndPaint(IntPtr hwnd, ref Paint paint);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern IntPtr LoadCursorW(IntPtr instance, IntPtr name);
    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern UIntPtr SetTimer(IntPtr hwnd, UIntPtr id, uint milliseconds, IntPtr callback);
    [DllImport("user32.dll", ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool KillTimer(IntPtr hwnd, UIntPtr id);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool SetProcessDpiAwarenessContext(IntPtr value);
    [DllImport("user32.dll", ExactSpelling = true)] private static extern IntPtr GetThreadDpiAwarenessContext();
    [DllImport("user32.dll", ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool AreDpiAwarenessContextsEqual(IntPtr a, IntPtr b);
    [DllImport("user32.dll", ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll", ExactSpelling = true)] private static extern IntPtr GetForegroundWindow();

    private static int Number(string value, int min, int max)
    {
        int number;
        if (!Int32.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out number) || number < min || number > max)
            throw new ArgumentException("Fixture geometry/lifetime is outside its bounded range.");
        return number;
    }

    private static Bitmap ReadPng()
    {
        FileInfo file = new FileInfo(imagePath);
        if (!file.Exists || file.Length > 8 * 1024 * 1024) throw new ArgumentException("Expected a bounded local PNG.");
        using (FileStream input = new FileStream(imagePath, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (Image source = Image.FromStream(input, true, true))
        {
            if (source.RawFormat.Guid != ImageFormat.Png.Guid || source.Width < 1 || source.Height < 1 || source.Width > 4096 || source.Height > 4096)
                throw new ArgumentException("Expected bounded PNG pixel dimensions.");
            // Clone before closing the stream; the fixture does not retain a file lock.
            return new Bitmap(source);
        }
    }

    private static void Ready()
    {
        string value = String.Format(CultureInfo.InvariantCulture,
            "{{\"protocol\":1,\"pid\":{0},\"hwnd\":{1},\"role\":\"{2}\",\"class_name\":\"{3}\",\"width\":{4},\"height\":{5},\"per_monitor_v2\":true,\"paint_count\":{6}}}",
            GetCurrentProcessId(), window.ToInt64(), role, className, width, height, paintCount);
        string temp = readyPath + ".tmp";
        File.WriteAllText(temp, value, new UTF8Encoding(false));
        // The Python observer may briefly hold the previous JSON without delete
        // sharing. Retry only this owned atomic publication, with a 250 ms cap.
        for (int attempt = 0; ; attempt++)
        {
            try
            {
                if (File.Exists(readyPath)) File.Replace(temp, readyPath, null);
                else File.Move(temp, readyPath);
                break;
            }
            catch (IOException) { if (attempt >= 10) throw; }
            catch (UnauthorizedAccessException) { if (attempt >= 10) throw; }
            System.Threading.Thread.Sleep(25);
        }
    }

    private static IntPtr Dispatch(IntPtr hwnd, uint message, UIntPtr wParam, IntPtr lParam)
    {
        try
        {
            switch (message)
            {
                case WM_ERASEBKGND: return new IntPtr(1);
                case WM_PAINT:
                    Paint paint;
                    IntPtr dc = BeginPaint(hwnd, out paint);
                    try
                    {
                        if (dc == IntPtr.Zero) throw new Win32Exception("Fixture BeginPaint failed.");
                        using (Graphics graphics = Graphics.FromHdc(dc))
                        {
                            graphics.Clear(Color.Black);
                            graphics.DrawImage(bitmap, new Rectangle(0, 0, width, height), 0, 0, bitmap.Width, bitmap.Height, GraphicsUnit.Pixel);
                        }
                        paintCount++;
                    }
                    finally { EndPaint(hwnd, ref paint); }
                    return IntPtr.Zero;
                case WM_RECREATE_OWNED:
                    CloseOwnedFocusSink();
                    // Allocate while the old HWND still exists, so the new handle
                    // cannot equal the old one. Keep PID/creation time unchanged.
                    IntPtr previous = window;
                    IntPtr replacement = CreateOwnedWindow();
                    recreating = true;
                    try
                    {
                        window = replacement;
                        if (!DestroyWindow(previous)) throw new Win32Exception("Fixture recreation destroy failed.");
                    }
                    finally { recreating = false; }
                    ShowOwnedWindow();
                    Ready();
                    return IntPtr.Zero;
                case WM_FOCUS_OWNED_SINK:
                    if (hwnd != window || role != "client" || noActivate ||
                        wParam != UIntPtr.Zero || lParam != IntPtr.Zero) return IntPtr.Zero;
                    if (focusSink == IntPtr.Zero)
                    {
                        // Ordinary, independent top-level window in this same
                        // foreground process. Never resize/hide the PNG client.
                        focusSink = CreateWindowExW(0, FocusSinkClass, FocusSinkTitle, 0x00C80000u,
                            0, 0, 160, 96, IntPtr.Zero, IntPtr.Zero, GetModuleHandleW(null), IntPtr.Zero);
                        if (focusSink == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
                    }
                    ShowWindow(focusSink, 5); // SW_SHOW
                    SetForegroundWindow(focusSink);
                    return focusSink;
                case WM_RETURN_OWNED_CLIENT:
                    if (hwnd != window || role != "client" || noActivate ||
                        wParam != UIntPtr.Zero || lParam != IntPtr.Zero || focusSink == IntPtr.Zero) return IntPtr.Zero;
                    // Switch while our sink still holds foreground permission,
                    // then close only that sink. No external window is targeted.
                    SetForegroundWindow(window);
                    CloseOwnedFocusSink();
                    return window == hwnd && focusSink == IntPtr.Zero && GetForegroundWindow() == hwnd ? new IntPtr(1) : IntPtr.Zero;
                case WM_TIMER:
                    if (Clock.ElapsedMilliseconds >= lifetime * 1000L) DestroyWindow(hwnd);
                    return IntPtr.Zero;
                case WM_CLOSE:
                    DestroyWindow(hwnd);
                    return IntPtr.Zero;
                case WM_DESTROY:
                    KillTimer(hwnd, new UIntPtr(1));
                    if (hwnd == window) window = IntPtr.Zero;
                    if (!recreating) PostQuitMessage(0);
                    return IntPtr.Zero;
            }
            return DefWindowProcW(hwnd, message, wParam, lParam);
        }
        catch (Exception error)
        {
            RecordError(error);
            PostQuitMessage(1); // Never propagate a managed exception through USER32.
            return IntPtr.Zero;
        }
    }

    private static IntPtr DispatchFocusSink(IntPtr hwnd, uint message, UIntPtr wParam, IntPtr lParam)
    {
        // Separate callback: closing this window cannot terminate the PNG fixture
        // or execute its paint, timer, recreation, or diagnostic commands.
        if (message == WM_DESTROY)
        {
            if (hwnd == focusSink) focusSink = IntPtr.Zero;
            return IntPtr.Zero;
        }
        // DefWindowProc handles ordinary painting and WM_CLOSE/DestroyWindow.
        return DefWindowProcW(hwnd, message, wParam, lParam);
    }

    private static void CloseOwnedFocusSink()
    {
        if (focusSink != IntPtr.Zero && !DestroyWindow(focusSink))
            throw new Win32Exception("Fixture focus sink destroy failed.");
    }

    private static IntPtr CreateOwnedWindow()
    {
        // Borderless own popup; the original image fills a bounded client area.
        // The foreign occluder stays nonactivating from its very first show.
        // Default client/game fixtures retain their original activation behavior.
        uint exStyle = noActivate ? 0x08000080u : 0u; // WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        IntPtr result = CreateWindowExW(exStyle, className, (role == "client" ? "League of Legends" : "VGA owned game fixture"), 0x80000000,
            x, y, width, height, IntPtr.Zero, IntPtr.Zero, GetModuleHandleW(null), IntPtr.Zero);
        if (result == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        return result;
    }

    private static void ShowOwnedWindow()
    {
        if (SetTimer(window, new UIntPtr(1), 1000, IntPtr.Zero) == UIntPtr.Zero)
            throw new Win32Exception(Marshal.GetLastWin32Error());
        int before = paintCount;
        ShowWindow(window, noActivate ? 4 : 5); // SW_SHOWNOACTIVATE / SW_SHOW
        if (!noActivate) SetForegroundWindow(window);
        UpdateWindow(window);
        if (paintCount <= before) throw new InvalidOperationException("Fixture has not painted its PNG.");
    }

    private static void RecordError(Exception error)
    {
        Console.Error.WriteLine(error.ToString());
        if (String.IsNullOrEmpty(readyPath)) return;
        try
        {
            string message = error.ToString();
            if (message.Length > 8000) message = message.Substring(0, 8000);
            File.WriteAllText(readyPath + ".error.txt", message, new UTF8Encoding(false));
        }
        catch (IOException) { } // Preserve the original startup/paint failure.
        catch (UnauthorizedAccessException) { }
    }

    [STAThread] private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 8 && args.Length != 9)
                throw new ArgumentException("Expected role PNG ready-json x y width height lifetime-seconds [noactivate].");
            if (args.Length == 9 && args[8] != "noactivate")
                throw new ArgumentException("Unknown fixture display option.");
            noActivate = args.Length == 9;
            role = args[0];
            if (role != "client" && role != "game") throw new ArgumentException("Unknown fixture role.");
            imagePath = Path.GetFullPath(args[1]); readyPath = Path.GetFullPath(args[2]);
            x = Number(args[3], 0, 4096); y = Number(args[4], 0, 4096);
            width = Number(args[5], 64, 1600); height = Number(args[6], 64, 1000);
            lifetime = Number(args[7], 1, 600);
            if (IntPtr.Size != 8 || Marshal.SizeOf(typeof(WindowClass)) != 80 ||
                Marshal.SizeOf(typeof(Message)) != 48 || Marshal.SizeOf(typeof(Paint)) != 72)
                throw new InvalidOperationException("Fixture requires verified x64 Win32 ABI layouts.");
            // Per-monitor-v2 applies only to this diagnostic process.
            if (!SetProcessDpiAwarenessContext(new IntPtr(-4)) ||
                !AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), new IntPtr(-4)))
                throw new Win32Exception("Fixture could not establish PMv2 DPI awareness.");
            bitmap = ReadPng();
            className = role == "game" ? "RiotWindowClass" : "Chrome_WidgetWin_1";
            WindowClass wc = new WindowClass();
            wc.cbSize = (uint)Marshal.SizeOf(typeof(WindowClass)); wc.lpfnWndProc = WindowProcedure;
            wc.hInstance = GetModuleHandleW(null); wc.lpszClassName = className;
            wc.hCursor = LoadCursorW(IntPtr.Zero, new IntPtr(32512));
            if (RegisterClassExW(ref wc) == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            if (role == "client" && !noActivate)
            {
                wc.lpfnWndProc = FocusSinkProcedure; wc.lpszClassName = FocusSinkClass;
                wc.hbrBackground = new IntPtr(6); // COLOR_WINDOW + 1; no PNG rendering.
                if (RegisterClassExW(ref wc) == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            window = CreateOwnedWindow();
            Clock.Start();
            ShowOwnedWindow();
            Ready();
            Message message;
            int status;
            while ((status = GetMessageW(out message, IntPtr.Zero, 0, 0)) > 0)
            {
                TranslateMessage(ref message); DispatchMessageW(ref message);
            }
            if (status < 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            return checked((int)message.wParam.ToUInt64());
        }
        catch (Exception error) { RecordError(error); return 1; }
        finally
        {
            // Cleanup also runs after startup/message-loop errors or main close.
            if (focusSink != IntPtr.Zero) DestroyWindow(focusSink);
            if (window != IntPtr.Zero) DestroyWindow(window);
            if (bitmap != null) bitmap.Dispose();
            GC.KeepAlive(WindowProcedure);
            GC.KeepAlive(FocusSinkProcedure);
        }
    }
}
