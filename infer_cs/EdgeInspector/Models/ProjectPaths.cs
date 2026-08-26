using System.IO;

namespace EdgeInspector.Models;

public static class ProjectPaths
{
    // 빌드 출력 위치(Debug/Release)에 관계없이 train/, infer_cs/를 모두 가진
    // C:\EdgeAI 루트를 상위 폴더로 거슬러 올라가며 찾는다.
    public static string? FindRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir.FullName, "train")) &&
                Directory.Exists(Path.Combine(dir.FullName, "infer_cs")))
                return dir.FullName;
            dir = dir.Parent;
        }
        return null;
    }
}
