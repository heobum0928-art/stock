namespace EdgeInspector.ViewModels;

// 모든 뷰(홈/라벨링/학습/검출/이상탐지/세그멘테이션)의 ViewModel을 묶는 최상위 컨테이너.
public sealed class ShellViewModel : IDisposable
{
    public HomeViewModel HomeVm { get; }
    public LabelingViewModel LabelingVm { get; }
    public SegLabelingViewModel SegLabelingVm { get; }
    public TrainingViewModel TrainingVm { get; }
    public MainViewModel EdgeVm { get; }
    public YoloViewModel YoloVm { get; }
    public AnomalyViewModel AnomalyVm { get; }

    public ShellViewModel(string? projectRoot, string? initialDomain = null)
    {
        HomeVm = new HomeViewModel(projectRoot);
        LabelingVm = new LabelingViewModel(projectRoot);
        SegLabelingVm = new SegLabelingViewModel(projectRoot);
        TrainingVm = new TrainingViewModel(projectRoot);
        EdgeVm = new MainViewModel(projectRoot);
        YoloVm = new YoloViewModel(projectRoot, initialDomain);
        AnomalyVm = new AnomalyViewModel(projectRoot);

        // 라벨링에서 데이터셋을 내보내면 학습 탭에 바로 연결.
        LabelingVm.DatasetExported += TrainingVm.SetDataset;
    }

    public void Dispose()
    {
        LabelingVm.SaveCurrent();      // 창 닫을 때 현재 라벨 저장(마지막 이미지 유실 방지)
        SegLabelingVm.SaveCurrent();   // 세그 라벨링도 동일 원칙(폴리곤/브러쉬 유실 방지)
        TrainingVm.Stop();             // 학습 중이면 자식 프로세스 정리
        EdgeVm.Dispose();
        YoloVm.Dispose();
        AnomalyVm.Dispose();
        SegLabelingVm.Dispose();
    }
}
