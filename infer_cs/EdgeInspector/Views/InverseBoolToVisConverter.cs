using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace EdgeInspector.Views;

// bool → Visibility 반전(true면 Collapsed). "이미지 없을 때만 안내 문구 보이기" 같은
// 빈 상태(empty-state) 바인딩에 사용.
public sealed class InverseBoolToVisConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        => (value is bool b && b) ? Visibility.Collapsed : Visibility.Visible;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        => throw new NotSupportedException();
}
