// Welcome to AetherIDE!
// This is a sample C# console application. Press F5 or click the Run button to execute.

using System;
using System.Collections.Generic;

namespace AetherRunner
{
    class Program
    {
        static void Main(string[] args)
        {
            Console.WriteLine("======================================");
            Console.WriteLine(" Hello from C# 10.0 and .NET Core!");
            Console.WriteLine("======================================");

            var languages = new List<string> { "C#", "Python", "HTML/CSS/JS" };
            
            Console.WriteLine("\nCurrently serving environments:");
            foreach (var lang in languages)
            {
                Console.WriteLine($" * {lang}");
            }

            Console.WriteLine($"\nSystem Time: {DateTime.Now}");
        }
    }
}
