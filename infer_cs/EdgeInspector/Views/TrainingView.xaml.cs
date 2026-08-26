using System.Windows;
using System.Windows.Controls;
using EdgeInspector.ViewModels;

namespace EdgeInspector.Views;

public partial class TrainingView : UserControl
{
    public TrainingView() => InitializeComponent();

    private TrainingViewModel? Vm => DataContext as TrainingViewModel;

    private void BrowseYaml_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.OpenFileDialog { Filter = "data.yaml|data.yaml;*.yaml;*.yml|모든 파일|*.*" };
        if (dlg.ShowDialog() == true)
            Vm?.PickDataYaml(dlg.FileName);
    }

    private void Start_Click(object sender, RoutedEventArgs e) => Vm?.Start();

    // 실수로 몇 십 분 진행된 학습을 날리는 걸 막기 위해 확인창을 거친다(이상탐지 학습
    // 시작 확인창과 대칭 — 파괴적 동작엔 항상 확인).
    private void Stop_Click(object sender, RoutedEventArgs e)
    {
        var r = MessageBox.Show("지금까지 진행된 학습을 중단할까요? 되돌릴 수 없습니다.",
            "학습 중단", MessageBoxButton.YesNo, MessageBoxImage.Warning, MessageBoxResult.No);
        if (r == MessageBoxResult.Yes) Vm?.Stop();
    }
}
