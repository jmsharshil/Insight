def num2words(n):
    """
    Convert a number into Indian Rupee words (up to Crores).
    """
    try:
        n = int(n)
    except ValueError:
        return ""

    if n == 0:
        return "Zero"

    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def convert_below_100(num):
        if num < 10:
            return units[num]
        elif num < 20:
            return teens[num - 10]
        else:
            return tens[num // 10] + (" " + units[num % 10] if num % 10 != 0 else "")

    def convert_below_1000(num):
        if num < 100:
            return convert_below_100(num)
        else:
            return units[num // 100] + " Hundred" + (" and " + convert_below_100(num % 100) if num % 100 != 0 else "")

    parts = []
    
    if n >= 10000000:
        crores = n // 10000000
        parts.append(convert_below_100(crores) + " Crore")
        n %= 10000000

    if n >= 100000:
        lakhs = n // 100000
        parts.append(convert_below_100(lakhs) + " Lakh")
        n %= 100000

    if n >= 1000:
        thousands = n // 1000
        parts.append(convert_below_100(thousands) + " Thousand")
        n %= 1000

    if n > 0:
        parts.append(convert_below_1000(n))

    return " ".join(parts).strip() + " Only"
