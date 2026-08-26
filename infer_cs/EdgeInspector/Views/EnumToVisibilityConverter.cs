using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace EdgeInspector.Views;

// enum 값의 이름이 ConverterParameter 문자열과 같으면 Visible, 아니면 Collapsed.
// (브러쉬 전용/매직브러쉬 전용 컨트롤을 Tool 값에 따라 보이거나 숨기는 데 사용 — SegLabelingView.)
public sealed class EnumToVisibilityConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
        => value?.ToString() == parameter?.ToString() ? Visibility.Visible : Visibility.Collapsed;

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => throw new NotSupportedException();
}
