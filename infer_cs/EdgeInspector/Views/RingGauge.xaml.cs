using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace EdgeInspector.Views;

// 정확도(mAP50) 등을 0~1 비율의 원형 게이지(링)로 표시. 상용 검사툴의 도넛차트 대응.
// Path의 ArcSegment를 코드에서 직접 계산(WPF엔 링 게이지 기본 컨트롤이 없음).
public partial class RingGauge : UserControl
{
    public static readonly DependencyProperty FractionProperty =
        DependencyProperty.Register(nameof(Fraction), typeof(double), typeof(RingGauge),
            new PropertyMetadata(0.0, OnChanged));

    public static readonly DependencyProperty CenterLabelProperty =
        DependencyProperty.Register(nameof(CenterLabel), typeof(string), typeof(RingGauge),
            new PropertyMetadata("—", OnLabelChanged));

    public double Fraction { get => (double)GetValue(FractionProperty); set => SetValue(FractionProperty, value); }
    public string CenterLabel { get => (string)GetValue(CenterLabelProperty); set => SetValue(CenterLabelProperty, value); }

    public RingGauge()
    {
        InitializeComponent();
        SizeChanged += (_, _) => Redraw();
        Loaded += (_, _) => Redraw();
    }

    private static void OnChanged(DependencyObject d, DependencyPropertyChangedEventArgs e) => ((RingGauge)d).Redraw();
    private static void OnLabelChanged(DependencyObject d, DependencyPropertyChangedEventArgs e) => ((RingGauge)d).CenterText.Text = (string)e.NewValue;

    private void Redraw()
    {
        double w = ActualWidth, h = ActualHeight;
        if (w <= 0 || h <= 0) { w = Width; h = Height; }
        if (w <= 0 || h <= 0) return;

        double stroke = 7;
        double r = Math.Min(w, h) / 2 - stroke / 2;
        var center = new Point(w / 2, h / 2);
        TrackRing.Width = TrackRing.Height = r * 2;

        double frac = Math.Max(0.0, Math.Min(1.0, Fraction));
        if (frac <= 0.001) { ProgressArc.Data = null; return; }

        double startAngle = -90; // 12시 방향에서 시작
        double sweep = frac * 360.0;
        double endAngle = startAngle + sweep;
        Point Pt(double angleDeg)
        {
            double rad = angleDeg * Math.PI / 180;
            return new Point(center.X + r * Math.Cos(rad), center.Y + r * Math.Sin(rad));
        }
        var start = Pt(startAngle);
        var end = Pt(endAngle);
        bool largeArc = sweep > 180;

        // 100%(완전한 원)면 ArcSegment가 시작=끝점이라 그려지지 않으므로 살짝 못 미치게 그린다.
        if (sweep >= 359.999) end = Pt(startAngle + 359.999);

        var figure = new PathFigure { StartPoint = start, IsClosed = false };
        figure.Segments.Add(new ArcSegment(end, new Size(r, r), 0, largeArc, SweepDirection.Clockwise, true));
        var geo = new PathGeometry();
        geo.Figures.Add(figure);
        ProgressArc.Data = geo;
    }
}
