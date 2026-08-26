using System.IO;
using Microsoft.ML.OnnxRuntime;

namespace EdgeInspector.Models;

// 날것의 .NET 예외 메시지(영문 스택/코덱 오류 등)는 비전공자에게 무의미하다.
// 흔한 원인을 "무엇을 하면 되는지"로 바꿔 안내하고, 원문은 괄호로 짧게 덧붙인다.
public static class FriendlyError
{
    public static string Describe(Exception ex)
    {
        string hint = ex switch
        {
            FileNotFoundException => "파일을 찾을 수 없습니다. 파일이 옮겨졌거나 삭제되지 않았는지 확인하세요.",
            DirectoryNotFoundException => "폴더를 찾을 수 없습니다. 경로가 바뀌지 않았는지 확인하세요.",
            UnauthorizedAccessException => "파일에 접근할 권한이 없습니다. 다른 프로그램이 쓰고 있거나 권한 문제일 수 있습니다.",
            IOException io when io.Message.Contains("being used by another process")
                => "파일이 다른 프로그램에서 열려 있습니다. 그 프로그램을 닫고 다시 시도하세요.",
            NotSupportedException => "지원하지 않는 파일 형식입니다. PNG·JPG·BMP 같은 일반 이미지인지 확인하세요.",
            OutOfMemoryException => "메모리가 부족합니다. 이미지가 너무 크거나 다른 프로그램이 많이 켜져 있을 수 있습니다.",
            // ONNX 모델 파일이 손상됐거나(다운로드 중단 등) 형식이 안 맞을 때 — protobuf
            // 파싱 예외 원문은 비전공자에게 완전히 무의미해서 별도 안내 추가.
            OnnxRuntimeException => "모델 파일이 손상되었거나 올바른 ONNX 형식이 아닙니다. 다시 export하거나 다른 모델 파일을 선택하세요.",
            _ => "예상치 못한 문제가 발생했습니다.",
        };
        return $"{hint} ({ex.Message})";
    }
}
