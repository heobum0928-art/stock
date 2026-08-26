using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace EdgeInspector.Views;

// 문자열이 비어있지 않으면 Visible, 비어있으면 Collapsed(파일명 표시용 구분점 등).
public sealed class StringToVisibilityConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
        => string.IsNullOrEmpty(value as string) ? Visibility.Collapsed : Visibility.Visible;

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => throw new NotSupportedException();
}
