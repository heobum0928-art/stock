using System.IO;
using System.Windows.Controls;
using Microsoft.Win32;
using EdgeInspector.ViewModels;

namespace EdgeInspector.Views;

public partial class YoloView : UserControl
{
    public YoloView() => InitializeComponent();

    private YoloViewModel? Vm => DataContext as YoloViewModel;

    private void OpenYoloImage_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        var dir = Vm?.SampleDirForOpen;
        var dlg = new OpenFileDialog
        {
            Filter = "이미지 (*.jpg;*.jpeg;*.png;*.bmp)|*.jpg;*.jpeg;*.png;*.bmp|모든 파일 (*.*)|*.*",
            InitialDirectory = dir != null && Directory.Exists(dir) ? dir : System.Environment.CurrentDirectory,
        };
        if (dlg.ShowDialog() == true) Vm?.LoadImage(dlg.FileName);
    }

    private void OpenReport_Click(object sender, System.Windows.RoutedEventArgs e) => Vm?.OpenReport();
    private void Benchmark_Click(object sender, System.Windows.RoutedEventArgs e) => Vm?.RunBenchmark();
}
