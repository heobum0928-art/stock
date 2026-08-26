using System.Windows;
using System.Windows.Controls;
using EdgeInspector.ViewModels;

namespace EdgeInspector.Views;

public partial class HomeView : UserControl
{
    // 모델 카드 클릭 시 셸에게 어느 뷰로 이동할지 알린다.
    public event Action<ModelCard>? CardActivated;
    // 워크플로우 카드(①라벨링/②학습) 클릭 시 셸에게 해당 탭으로 이동을 요청한다.
    // 예전엔 별도 파이썬 tkinter 창을 띄웠지만, 이제 EdgeInspector 안의 탭으로 통합됐다.
    public event Action? LabelStepRequested;
    public event Action? TrainStepRequested;

    public HomeView() => InitializeComponent();

    private void Card_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is ModelCard card)
            CardActivated?.Invoke(card);
    }

    private void StepLabel_Click(object sender, RoutedEventArgs e) => LabelStepRequested?.Invoke();
    private void StepTrain_Click(object sender, RoutedEventArgs e) => TrainStepRequested?.Invoke();

    private HomeViewModel? Vm => DataContext as HomeViewModel;

    // 옛 tkinter 런처의 웹캠 데모/건강검진을 이 앱에서 바로 실행(프로그램 하나로 통합).
    private void WebcamDemo_Click(object sender, RoutedEventArgs e)
    {
        var err = Vm?.LaunchWebcamDemo();
        if (err != null) MessageBox.Show(err, "웹캠 데모", MessageBoxButton.OK, MessageBoxImage.Warning);
        else MessageBox.Show("웹캠 데모 창을 실행했습니다. 잠시 후 별도 창이 열립니다.\n(창에서 슬라이더로 대상/민감도 조절, ESC로 종료)",
            "웹캠 데모", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private void HealthCheck_Click(object sender, RoutedEventArgs e)
    {
        var err = Vm?.RunHealthCheck();
        if (err != null) MessageBox.Show(err, "모델 상태 점검", MessageBoxButton.OK, MessageBoxImage.Warning);
        else MessageBox.Show("모델 상태 점검 리포트를 생성해 브라우저로 엽니다. 잠시만 기다려주세요.",
            "모델 상태 점검", MessageBoxButton.OK, MessageBoxImage.Information);
    }
    private void StepInspect_Click(object sender, RoutedEventArgs e) =>
        MessageBox.Show("아래 '내 모델'에서 검사할 모델 카드를 클릭하면 해당 뷰어로 이동합니다.",
            "검사", MessageBoxButton.OK, MessageBoxImage.Information);
}
