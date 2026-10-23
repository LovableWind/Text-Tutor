using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

// 旁批的启动器：双击就起服务，不弹黑窗口。
// 出问题时不弹框（弹框会挡住无头环境），一律写进 data\launcher.log。
static class Launcher
{
    static string logPath;

    static void Log(string msg)
    {
        try
        {
            if (logPath != null)
                File.AppendAllText(logPath, DateTime.Now.ToString("HH:mm:ss ") + msg + "\r\n");
        }
        catch { }
    }

    [STAThread]
    static void Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string internalDir = Path.Combine(root, "_internal");
        string pyw = Path.Combine(Path.Combine(internalDir, "runtime"), "pythonw.exe");
        string server = Path.Combine(Path.Combine(internalDir, "app"), "server.py");
        string data = Path.Combine(root, "data");

        try { Directory.CreateDirectory(data); } catch { }
        logPath = Path.Combine(data, "launcher.log");
        Log("start root=" + root);
        Log("pythonw=" + pyw + " exists=" + File.Exists(pyw));
        Log("server=" + server + " exists=" + File.Exists(server));

        if (!File.Exists(pyw) || !File.Exists(server))
        {
            Log("missing files, abort");
            MessageBox.Show(
                "找不到程序文件：\n_internal\\runtime\\pythonw.exe\n_internal\\app\\server.py\n\n" +
                "请解压整个压缩包，不要只复制其中几个文件。",
                "旁批 · 讲义伴读",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning);
            return;
        }

        // 首次运行：去掉 Windows 给下载文件打的“来自 Internet”标记
        string marker = Path.Combine(data, ".unblocked");
        if (!File.Exists(marker))
        {
            try
            {
                ProcessStartInfo ps = new ProcessStartInfo("powershell.exe",
                    "-NoProfile -ExecutionPolicy Bypass -Command \"Get-ChildItem -LiteralPath '" +
                    root.Replace("'", "''") + "' -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue\"");
                ps.UseShellExecute = false;
                ps.CreateNoWindow = true;
                ps.WindowStyle = ProcessWindowStyle.Hidden;
                Log("unblock: starting powershell");
                Process p = Process.Start(ps);
                if (p != null) p.WaitForExit(4000);
                File.WriteAllText(marker, "ok");
                Log("unblock done");
            }
            catch (Exception ex) { Log("unblock failed: " + ex.Message); }
        }

        try
        {
            ProcessStartInfo psi = new ProcessStartInfo(pyw);
            psi.Arguments = "\"" + server + "\" --data-dir \"" + data + "\"";
            psi.WorkingDirectory = root;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            Process proc = Process.Start(psi);
            Log("server started pid=" + (proc == null ? "null" : proc.Id.ToString()));
        }
        catch (Exception ex)
        {
            Log("start failed: " + ex.Message);
            MessageBox.Show("启动失败：" + ex.Message, "旁批 · 讲义伴读",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
