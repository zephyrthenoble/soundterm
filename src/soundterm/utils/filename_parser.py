import re


class SmartParser:
    """Unfortunately made using AI, this doesn't work very well. It tries to be too smart and ends up being too dumb."""

    def __init__(self):
        # Configuration for specific types
        self.type_patterns = {
            "s": r".+?",  # Non-greedy string
            "S": r".+",  # Greedy string
            "i": r"\d+",  # Variable integer
            "f": r"\d+\.?\d*",  # Float
        }

    def _build_regex(self, template):
        # Regex to find {name} OR {name:type} OR {name:typeN}
        # Matches: { (name) (optional : followed by type and optional digits) }
        tag_regex = r"\{(\w+)(?::([sSif])(\d+)?)?\}"

        print(f"[SmartParser] Building regex from template: {template}")
        regex_string = re.escape(template)
        # Unescape only the braces for our secondary scan
        regex_string = regex_string.replace(r"\{", "{").replace(r"\}", "}")

        matches = list(re.finditer(tag_regex, template))
        print(f"[SmartParser] Found {len(matches)} template tags")
        if len(matches) == 0:
            print(
                "[SmartParser] No template tags found. Using escaped template as regex."
            )
            return f"^{regex_string}$"

        # Replace from right to left to maintain index integrity
        for match in reversed(matches):
            full_tag = match.group(0)
            name = match.group(1)
            type_char = match.group(2) or "s"  # Default to 's' (string)
            length = match.group(3)

            print(
                f"[SmartParser]   Tag: {full_tag} -> name={name}, type={type_char}, length={length}"
            )

            # Build specific pattern
            if type_char == "i" and length:
                pattern = rf"\d{{{length}}}"
            else:
                pattern = self.type_patterns[type_char]

            replacement = rf"(?P<{name}>{pattern})"
            regex_string = regex_string.replace(full_tag, replacement)

        final_pattern = f"^{regex_string}$"
        print(f"[SmartParser] Final regex pattern: {final_pattern}")
        return final_pattern

    def parse(self, template, filename):
        # Remove extension before matching
        from pathlib import Path

        name_only = Path(filename).stem

        print(f"[SmartParser] Parsing filename: {filename}")
        print(f"[SmartParser] Name without extension: {name_only}")

        # pattern = self._build_regex(template)
        pattern = template
        print(f"[SmartParser] Using regex pattern: {name_only} -> {pattern}")
        match = re.match(pattern, name_only)

        if not match:
            print("[SmartParser] ❌ No match found")
            return None

        print(f"[SmartParser] ✓ Match found: {match.groupdict()}")

        # Automatic type casting based on the template used
        results = match.groupdict()
        tag_info = re.findall(r"\{(\w+)(?::([sSif])\d?)?\}", template)

        for name, type_char in tag_info:
            type_char = type_char or "s"
            if type_char == "i":
                print(
                    f"[SmartParser] Converting '{name}' to int: {results[name]} -> {int(results[name])}"
                )
                results[name] = int(results[name])
            elif type_char == "f":
                print(
                    f"[SmartParser] Converting '{name}' to float: {results[name]} -> {float(results[name])}"
                )
                results[name] = float(results[name])

        print(f"[SmartParser] Final parsed result: {results}")
        return results
