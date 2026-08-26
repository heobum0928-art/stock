using System.IO;
using System.Text.Json;

namespace EdgeInspector.Models;

// examples/<도메인>의 학습된 ONNX + 클래스 목록 + 검증 이미지 폴더를 한 데 묶은 정의.
// 프로젝트 루트의 domains.json에서 읽는다 — training_wizard.py(학습 마법사)가 새 도메인을
// 학습할 때마다 이 파일에 항목을 append하면, C# 재빌드 없이 뷰어 드롭다운에 바로 나타난다.
// 학습 이력 메타(선택). 학습 마법사가 domains.json 각 항목에 함께 기록한다.
// 없어도 뷰어는 정상 동작(전부 nullable). System.Text.Json이 채워준다.
public sealed class YoloMeta
{
    public string? Created { get; init; }
    public string? Model { get; init; }
    public int? Epochs { get; init; }
    public int? NTrain { get; init; }
    public int? NClasses { get; init; }
    public double? MAP50 { get; init; }
    public string? DatasetPath { get; init; }
    public string? ReportRelPath { get; init; }   // examples/<도메인>/eval_report.html (선택)
    public string? Note { get; init; }

    // 상태줄에 한 줄로 요약(있는 값만).
    public string Summary()
    {
        var parts = new List<string>();
        if (MAP50 is double m) parts.Add($"정확도(mAP50) {m * 100:F1}%");
        if (!string.IsNullOrEmpty(Model)) parts.Add($"모델 {Model}");
        if (NTrain is int n) parts.Add($"학습 {n}장");
        if (!string.IsNullOrEmpty(Created)) parts.Add($"학습일 {Created}");
        else if (!string.IsNullOrEmpty(Note)) parts.Add(Note!);
        return string.Join("  ·  ", parts);
    }
}

public sealed class YoloDomain
{
    public required string DisplayName { get; init; }
    public required string OnnxRelPath { get; init; }      // 프로젝트 루트 기준 상대경로
    public required string SampleDirRelPath { get; init; }
    public required string[] ClassNames { get; init; }
    public YoloMeta? Meta { get; init; }                   // 학습 이력(선택)

    public override string ToString() => DisplayName;

    public string ResolveOnnx(string root) => Path.Combine(root, OnnxRelPath.Replace('/', Path.DirectorySeparatorChar));
    public string ResolveSampleDir(string root) => Path.Combine(root, SampleDirRelPath.Replace('/', Path.DirectorySeparatorChar));

    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true };

    // domains.json이 없거나 읽기 실패하면 빈 목록을 반환한다(뷰어가 "도메인 없음" 상태로
    // 조용히 처리 — 크래시하지 않음. 학습 마법사를 아직 한 번도 안 돌렸거나 domains.json이
    // 삭제된 경우에도 EdgeInspector 자체는 정상 실행돼야 하므로).
    public static IReadOnlyList<YoloDomain> Load(string? projectRoot)
    {
        if (projectRoot == null)
            return Array.Empty<YoloDomain>();

        var path = Path.Combine(projectRoot, "domains.json");
        if (!File.Exists(path))
            return Array.Empty<YoloDomain>();

        try
        {
            var json = File.ReadAllText(path);
            var domains = JsonSerializer.Deserialize<List<YoloDomain>>(json, JsonOptions);
            return domains ?? new List<YoloDomain>();
        }
        catch (Exception)
        {
            return Array.Empty<YoloDomain>();
        }
    }
}
