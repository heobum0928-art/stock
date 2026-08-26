using System.IO;
using System.Windows.Controls;
using Microsoft.Win32;
using EdgeInspector.Models;
using EdgeInspector.ViewModels;

namespace EdgeInspector.Views;

public partial class SegmentationView : UserControl
{
    public SegmentationView() => InitializeComponent();

    private MainViewModel? Vm => DataContext as MainViewModel;

    private void OpenModel_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        var root = ProjectPaths.FindRoot();
        var dlg = new OpenFileDialog
        {
            Filter = "ONNX 모델 (*.onnx)|*.onnx",
            InitialDirectory = root != null ? Path.Combine(root, "train") : System.Environment.CurrentDirectory,
        };
        if (dlg.ShowDialog() == true) Vm?.LoadModel(dlg.FileName);
    }

    private void OpenImage_Click(object sender, System.Windows.RoutedEventArgs e)
    {
        var root = ProjectPaths.FindRoot();
        var dir = root != null ? Path.Combine(root, "train", "data", "images") : System.Environment.CurrentDirectory;
        var dlg = new OpenFileDialog
        {
            Filter = "이미지 (*.png;*.bmp;*.jpg;*.jpeg)|*.png;*.bmp;*.jpg;*.jpeg|모든 파일 (*.*)|*.*",
            InitialDirectory = Directory.Exists(dir) ? dir : System.Environment.CurrentDirectory,
        };
        if (dlg.ShowDialog() == true) Vm?.LoadImage(dlg.FileName);
    }
}
