---
name: math-calculator
description: Perform calculations, data analysis, and numerical problem-solving. Use when the user asks for math, percentages, statistics, unit conversions, or any computation.
---

# Math & Computation

Perform calculations, data analysis, and numerical problem-solving using the code interpreter.

## Approach

1. Understand the mathematical problem or calculation request
2. Write Python code to solve it using the code interpreter
3. Execute the code and verify the result
4. Present the answer clearly with explanation

## Use the Code Interpreter

Always use the `code_interpreter` tool to run Python code for calculations. This gives you access to:

- Full Python standard library (`math`, `statistics`, `decimal`, etc.)
- NumPy for numerical operations
- Accurate floating-point arithmetic
- Complex multi-step computations

## Example Code Patterns

```python
# Basic math
result = (15 * 3.5) + (22 / 4)

# Statistics
import statistics
data = [23, 45, 67, 89, 12]
mean = statistics.mean(data)
median = statistics.median(data)

# Percentages
total = 250
percentage = 15
result = total * (percentage / 100)

# Unit conversions
celsius = 32
fahrenheit = (celsius * 9/5) + 32
```

## Response Guidelines

- Show the code you ran
- Present the final answer clearly
- Explain the calculation if it's non-trivial
- Round appropriately based on context
- Include units when applicable
