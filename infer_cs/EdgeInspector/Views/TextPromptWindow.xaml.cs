using System.Windows;
using System.Windows.Input;

namespace EdgeInspector.Views;

// WinForms InputBox 대신 테마에 맞춘 최소 입력 다이얼로그(클래스 이름 변경 등에 재사용).
public partial class TextPromptWindow : Window
{
    public string? Result { get; private set; }

    public TextPromptWindow(string prompt, string initialValue)
    {
        InitializeComponent();
        PromptLabel.Text = prompt;
        Input.Text = initialValue;
        Loaded += (_, _) => { Input.Focus(); Input.SelectAll(); };
    }

    // owner 창 위 중앙에 뜨는 이름변경 다이얼로그. 확인을 누르면 새 이름, 취소/닫기면 null.
    public static string? Ask(Window owner, string prompt, string initialValue)
    {
        var w = new TextPromptWindow(prompt, initialValue) { Owner = owner };
        return w.ShowDialog() == true ? w.Result : null;
    }

    private void Ok_Click(object sender, RoutedEventArgs e)
    {
        Result = Input.Text.Trim();
        DialogResult = true;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => DialogResult = false;

    private void Input_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter) { Result = Input.Text.Trim(); DialogResult = true; }
        else if (e.Key == Key.Escape) DialogResult = false;
    }
}
