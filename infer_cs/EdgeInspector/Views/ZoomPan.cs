using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace EdgeInspector.Views;

// 뷰어 이미지에 마우스휠 줌 + 드래그 팬 + 더블클릭 리셋을 붙이는 재사용 첨부 동작.
// 검사툴의 핵심 상호작용(결함을 확대해 확인). 대상 Grid에 local:ZoomPan.Enabled="True".
public static class ZoomPan
{
    public static readonly DependencyProperty EnabledProperty =
        DependencyProperty.RegisterAttached("Enabled", typeof(bool), typeof(ZoomPan),
            new PropertyMetadata(false, OnEnabledChanged));

    public static void SetEnabled(DependencyObject o, bool v) => o.SetValue(EnabledProperty, v);
    public static bool GetEnabled(DependencyObject o) => (bool)o.GetValue(EnabledProperty);

    private static void OnEnabledChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not FrameworkElement fe || !(bool)e.NewValue) return;

        var scale = new ScaleTransform(1, 1);
        var translate = new TranslateTransform(0, 0);
        var group = new TransformGroup();
        group.Children.Add(scale);
        group.Children.Add(translate);
        fe.RenderTransform = group;
        if (fe is Panel p && p.Background == null) p.Background = Brushes.Transparent; // 빈 영역도 히트되게

        Point start = default; bool dragging = false;

        fe.MouseWheel += (_, ev) =>
        {
            double factor = ev.Delta > 0 ? 1.15 : 1 / 1.15;
            double newScale = Math.Clamp(scale.ScaleX * factor, 1.0, 12.0);
            factor = newScale / scale.ScaleX;
            if (Math.Abs(factor - 1) < 1e-6) return;
            var pos = ev.GetPosition(fe);
            // 커서 지점을 중심으로 확대(줌-투-커서)
            translate.X = (translate.X - pos.X) * factor + pos.X;
            translate.Y = (translate.Y - pos.Y) * factor + pos.Y;
            scale.ScaleX = scale.ScaleY = newScale;
        };
        fe.MouseLeftButtonDown += (_, ev) =>
        {
            if (scale.ScaleX <= 1.0001) return;   // 확대 상태에서만 팬
            start = ev.GetPosition(fe);
            dragging = fe.CaptureMouse();
            fe.Cursor = Cursors.SizeAll;
        };
        fe.MouseMove += (_, ev) =>
        {
            if (!dragging) return;
            var pos = ev.GetPosition(fe);
            translate.X += (pos.X - start.X) * scale.ScaleX;
            translate.Y += (pos.Y - start.Y) * scale.ScaleY;
            start = pos;
        };
        fe.MouseLeftButtonUp += (_, _) => { dragging = false; fe.ReleaseMouseCapture(); fe.Cursor = Cursors.Arrow; };
        fe.MouseRightButtonDown += (_, _) => Reset(scale, translate);
        fe.MouseLeftButtonDown += (_, ev) => { if (ev.ClickCount == 2) Reset(scale, translate); };
    }

    private static void Reset(ScaleTransform s, TranslateTransform t)
    {
        s.ScaleX = s.ScaleY = 1; t.X = t.Y = 0;
    }
}
