using System.IO;
using System.Windows.Controls;
using Microsoft.Win32;
using EdgeInspector.ViewModels;

namespace EdgeInspector.Views;

public partial class AnomalyView : UserControl
{
    public AnomalyView() => InitializeComponent();

    private AnomalyViewModel? Vm => DataContext as AnomalyViewModel;

    private void OpenImage_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        var dir = Vm?.SampleDirForOpen;
        var dlg = new OpenFileDialog
        {
            Filter = "이미지 (*.png;*.bmp;*.jpg;*.jpeg)|*.png;*.bmp;*.jpg;*.jpeg|모든 파일 (*.*)|*.*",
            InitialDirectory = dir != null && Directory.Exists(dir) ? dir : System.Environment.CurrentDirectory,
        };
        if (dlg.ShowDialog() == true) Vm?.LoadImage(dlg.FileName);
    }

    // 검사할 이미지 폴더를 통째로 열어 갤러리에 채운다(여러 장 연속 검사).
    private void OpenFolder_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        using var dlg = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "검사할 이미지가 든 폴더를 선택하세요",
        };
        if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
            Vm?.OpenFolder(dlg.SelectedPath);
    }

    // 진단용: 학습 버튼 흐름의 각 단계를 파일로 남긴다(어디서 멈추는지 사후 확인).
    private static void Trace(string msg)
    {
        try
        {
            var dir = @"C:\EdgeAI\logs";
            Directory.CreateDirectory(dir);
            File.AppendAllText(Path.Combine(dir, "anomaly_click_trace.txt"),
                $"{DateTime.Now:HH:mm:ss}  {msg}\n");
        }
        catch { }
    }

    // 양품(정상) 이미지만 든 폴더를 골라 새 이상탐지 모델 학습.
    private void TrainNew_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        Trace("① 버튼 클릭됨");
        if (Vm == null) { Trace("✗ Vm==null 반환"); return; }
        using var dlg = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "양품(정상) 이미지만 든 폴더를 선택하세요 (라벨/박스 필요 없음)",
        };
        Trace("② 폴더 선택창 여는 중");
        if (dlg.ShowDialog() != System.Windows.Forms.DialogResult.OK) { Trace("✗ 폴더선택 취소/닫힘"); return; }

        var folder = dlg.SelectedPath;
        Trace($"③ 폴더 선택됨: {folder}");
        // 이미지 개수 간단 점검 — 너무 적으면 안내(최소 10장 권장, 수십~수백 장이 이상적).
        var exts = new[] { ".jpg", ".jpeg", ".png", ".bmp" };
        int n;
        try
        {
            n = Directory.EnumerateFiles(folder).Count(f => exts.Contains(Path.GetExtension(f).ToLowerInvariant()));
        }
        catch { n = 0; }
        Trace($"④ 이미지 {n}장 발견");
        if (n == 0)
        {
            System.Windows.MessageBox.Show("선택한 폴더에 이미지가 없습니다. 하위 폴더가 아니라 이미지가 바로 든 폴더를 고르세요.",
                "이미지 없음", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
            return;
        }

        var name = TextPromptWindow.Ask(System.Windows.Window.GetWindow(this),
            "새 모델 이름(영문/숫자):", "mycheck");
        Trace($"⑤ 이름 입력: '{name ?? "(취소)"}'");
        if (string.IsNullOrWhiteSpace(name)) { Trace("✗ 이름 비어서 반환"); return; }
        if (!System.Text.RegularExpressions.Regex.IsMatch(name, "^[A-Za-z0-9_]+$"))
        {
            System.Windows.MessageBox.Show("모델 이름은 영문/숫자/밑줄만 됩니다(예: mycheck).",
                "이름 확인", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
            return;
        }

        // 같은 이름의 모델이 이미 있으면 조용히 덮어쓰지 않고 먼저 확인받는다.
        if (Vm.AvailableModels.Contains(name))
        {
            var overwrite = System.Windows.MessageBox.Show(
                $"'{name}' 모델이 이미 있습니다. 덮어쓰고 다시 학습할까요?",
                "모델 이름 중복", System.Windows.MessageBoxButton.YesNo, System.Windows.MessageBoxImage.Warning, System.Windows.MessageBoxResult.No);
            Trace($"⑤-1 이름 중복 확인 결과: {overwrite}");
            if (overwrite != System.Windows.MessageBoxResult.Yes) { Trace("✗ 덮어쓰기 취소로 반환"); return; }
        }

        var warn = n < 10 ? $"\n\n⚠ 지금 {n}장뿐입니다. 정확한 검사를 위해선 양품 수십~수백 장을 권장합니다." : "";
        var ok = System.Windows.MessageBox.Show(
            $"'{folder}'의 양품 이미지 {n}장으로 이상탐지 모델을 학습합니다.\n라벨(박스)은 필요 없습니다.{warn}\n\n" +
            "처음 실행 시 라이브러리 로딩으로 수 분 걸릴 수 있습니다. 시작할까요?",
            "이상탐지 학습", System.Windows.MessageBoxButton.OKCancel, System.Windows.MessageBoxImage.Question);
        Trace($"⑥ 확인창 결과: {ok}");
        if (ok == System.Windows.MessageBoxResult.OK)
        {
            Trace("⑦ TrainNewModel 호출 → 학습 프로세스 시작");
            Vm.TrainNewModel(folder, name);
        }
        else Trace("✗ 확인창에서 취소");
    }

    // 지금 보고 있는 이미지를(과검/미검 리포트 대신) 그 모델의 양품 폴더에 바로 추가.
    // 그 모델이 어느 폴더로 학습됐는지 처음 알 땐 폴더선택창으로 한 번만 받고, 이후엔
    // ViewModel이 기억해서 자동으로 그 폴더를 쓴다.
    private void AddRetrainCandidate_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (Vm == null) return;
        var modelName = Vm.SelectedModelName;
        if (string.IsNullOrWhiteSpace(modelName))
        {
            System.Windows.MessageBox.Show("먼저 모델을 선택하세요.", "모델 없음",
                System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
            return;
        }

        var normalDir = Vm.NormalDirForModel(modelName);
        if (normalDir == null)
        {
            using var dlg = new System.Windows.Forms.FolderBrowserDialog
            {
                Description = $"'{modelName}' 모델을 학습할 때 쓴 양품(정상) 폴더를 선택하세요 (한 번만 물어봅니다)",
            };
            if (dlg.ShowDialog() != System.Windows.Forms.DialogResult.OK) return;
            normalDir = dlg.SelectedPath;
        }

        var err = Vm.AddCurrentImageToRetrainSet(normalDir);
        if (err != null)
            System.Windows.MessageBox.Show(err, "추가 실패", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
    }

    // 미검(실제 불량인데 OK로 나온 이미지) 기록 — 양품 폴더에 넣는 게 아니라 별도
    // 회귀테스트 목록에만 남긴다(AddRetrainCandidate_Click과 정반대 처리).
    private void AddConfirmedDefect_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        if (Vm == null) return;
        var err = Vm.AddCurrentImageToConfirmedDefects();
        if (err != null)
            System.Windows.MessageBox.Show(err, "기록 실패", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
    }

    private void CancelTrain_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        var r = System.Windows.MessageBox.Show("진행 중인 학습을 취소할까요? 지금까지 학습한 내용은 저장되지 않습니다.",
            "학습 취소", System.Windows.MessageBoxButton.YesNo, System.Windows.MessageBoxImage.Warning, System.Windows.MessageBoxResult.No);
        if (r == System.Windows.MessageBoxResult.Yes) Vm?.CancelTraining();
    }

    private void DeleteModel_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        var name = Vm?.SelectedModelName;
        if (string.IsNullOrWhiteSpace(name)) return;
        var r = System.Windows.MessageBox.Show(
            $"'{name}' 모델을 삭제할까요?\n학습에 쓰인 체크포인트·로그까지 함께 삭제되며 되돌릴 수 없습니다.\n다시 쓰려면 양품 폴더로 재학습해야 합니다.",
            "모델 삭제", System.Windows.MessageBoxButton.YesNo, System.Windows.MessageBoxImage.Warning, System.Windows.MessageBoxResult.No);
        if (r != System.Windows.MessageBoxResult.Yes) return;
        var err = Vm?.DeleteModel(name);
        if (err != null)
            System.Windows.MessageBox.Show(err, "삭제 실패", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
    }
}
