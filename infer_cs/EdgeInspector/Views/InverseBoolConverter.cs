using System.Globalization;
using System.Windows.Data;

namespace EdgeInspector.Views;

// bool 반전(true→false). IsEnabled="{Binding IsBusy, Converter=InverseBool}" 처럼
// "바쁠 때 비활성화" 바인딩에 사용.
public sealed class InverseBoolConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        => value is bool b ? !b : true;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        => value is bool b ? !b : false;
}
