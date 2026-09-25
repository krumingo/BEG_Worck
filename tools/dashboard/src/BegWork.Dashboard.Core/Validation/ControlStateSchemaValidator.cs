using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace BegWork.Dashboard.Core.Validation;

/// <summary>
/// Structural validation of a control-state document against
/// <c>coordination/CONTROL_STATE.schema.json</c>.
///
/// This is a deliberate port of the subset of JSON Schema that
/// <c>tools/control_engine.py:_check_schema</c> implements, so the dashboard
/// accepts exactly what the producer's own validator accepts — no more. Using a
/// third-party schema engine would silently widen or narrow that contract, which
/// for a read-model whose whole job is to refuse unverified data is the wrong
/// trade. Anything structurally wrong is INVALID; the dashboard shows the failure
/// instead of a partially-bound card.
/// </summary>
public static class ControlStateSchemaValidator
{
    public static VerificationResult Validate(JsonElement state, JsonElement schema)
    {
        var failures = new List<VerificationFinding>();
        try
        {
            Check(state, schema, schema, "$state");
        }
        catch (SchemaViolation violation)
        {
            failures.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "SCHEMA", violation.Message));
        }
        return VerificationResult.From(failures);
    }

    private sealed class SchemaViolation(string message) : Exception(message);

    private static bool Matches(JsonElement value, JsonElement rule, JsonElement root)
    {
        try
        {
            Check(value, rule, root, "$branch");
            return true;
        }
        catch (SchemaViolation)
        {
            return false;
        }
    }

    private static void Check(JsonElement value, JsonElement rule, JsonElement root, string location)
    {
        if (rule.TryGetProperty("$ref", out var reference))
        {
            var name = reference.GetString()!.Replace("#/$defs/", string.Empty);
            Check(value, root.GetProperty("$defs").GetProperty(name), root, location);
            return;
        }

        if (rule.TryGetProperty("anyOf", out var anyOf))
        {
            if (!anyOf.EnumerateArray().Any(part => Matches(value, part, root)))
            {
                throw new SchemaViolation($"{location}: no anyOf branch matches");
            }
            return;
        }

        if (rule.TryGetProperty("const", out var constant) && !SameJson(value, constant))
        {
            throw new SchemaViolation($"{location}: expected {Describe(constant)}");
        }

        if (rule.TryGetProperty("enum", out var choices)
            && !choices.EnumerateArray().Any(choice => SameJson(value, choice)))
        {
            throw new SchemaViolation($"{location}: invalid enum value {Describe(value)}");
        }

        CheckType(value, rule, location);
        CheckObject(value, rule, root, location);
        CheckArray(value, rule, root, location);
        CheckString(value, rule, location);
        CheckNumber(value, rule, location);
    }

    private static void CheckType(JsonElement value, JsonElement rule, string location)
    {
        if (!rule.TryGetProperty("type", out var typeRule))
        {
            return;
        }

        var kinds = typeRule.ValueKind == JsonValueKind.String
            ? [typeRule.GetString()!]
            : typeRule.EnumerateArray().Select(item => item.GetString()!).ToArray();

        if (!kinds.Any(kind => IsKind(value, kind)))
        {
            throw new SchemaViolation($"{location}: wrong type");
        }
    }

    private static bool IsKind(JsonElement value, string kind) => kind switch
    {
        "object" => value.ValueKind == JsonValueKind.Object,
        "array" => value.ValueKind == JsonValueKind.Array,
        "string" => value.ValueKind == JsonValueKind.String,
        "integer" => IsInteger(value),
        "boolean" => value.ValueKind is JsonValueKind.True or JsonValueKind.False,
        "null" => value.ValueKind == JsonValueKind.Null,
        _ => false,
    };

    // JSON booleans must not satisfy "integer"; this mirrors Python's `type(x) is int`.
    private static bool IsInteger(JsonElement value) =>
        value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out _);

    private static void CheckObject(JsonElement value, JsonElement rule, JsonElement root, string location)
    {
        if (value.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        var present = value.EnumerateObject().Select(p => p.Name).ToHashSet(StringComparer.Ordinal);

        if (rule.TryGetProperty("required", out var required))
        {
            var missing = required.EnumerateArray()
                .Select(item => item.GetString()!)
                .Where(name => !present.Contains(name))
                .OrderBy(name => name, StringComparer.Ordinal)
                .ToList();
            if (missing.Count > 0)
            {
                throw new SchemaViolation($"{location}: missing [{string.Join(", ", missing)}]");
            }
        }

        var properties = rule.TryGetProperty("properties", out var props)
            ? props
            : default;
        var known = properties.ValueKind == JsonValueKind.Object
            ? properties.EnumerateObject().Select(p => p.Name).ToHashSet(StringComparer.Ordinal)
            : [];

        if (rule.TryGetProperty("additionalProperties", out var extra)
            && extra.ValueKind == JsonValueKind.False)
        {
            var unknown = present.Except(known).OrderBy(name => name, StringComparer.Ordinal).ToList();
            if (unknown.Count > 0)
            {
                throw new SchemaViolation($"{location}: unknown fields [{string.Join(", ", unknown)}]");
            }
        }

        if (properties.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        foreach (var member in value.EnumerateObject())
        {
            if (properties.TryGetProperty(member.Name, out var childRule))
            {
                Check(member.Value, childRule, root, $"{location}.{member.Name}");
            }
        }
    }

    private static void CheckArray(JsonElement value, JsonElement rule, JsonElement root, string location)
    {
        if (value.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        var items = value.EnumerateArray().ToList();
        var min = rule.TryGetProperty("minItems", out var minItems) ? minItems.GetInt32() : 0;
        var max = rule.TryGetProperty("maxItems", out var maxItems) ? maxItems.GetInt32() : int.MaxValue;
        if (items.Count < min || items.Count > max)
        {
            throw new SchemaViolation($"{location}: wrong item count");
        }

        if (rule.TryGetProperty("uniqueItems", out var unique)
            && unique.ValueKind == JsonValueKind.True
            && items.Select(item => item.GetRawText()).Distinct(StringComparer.Ordinal).Count() != items.Count)
        {
            throw new SchemaViolation($"{location}: duplicate items");
        }

        if (!rule.TryGetProperty("items", out var itemRule))
        {
            return;
        }

        for (var index = 0; index < items.Count; index++)
        {
            Check(items[index], itemRule, root, $"{location}[{index}]");
        }
    }

    private static void CheckString(JsonElement value, JsonElement rule, string location)
    {
        if (value.ValueKind != JsonValueKind.String)
        {
            return;
        }

        var text = value.GetString() ?? string.Empty;

        // Unanchored, matching Python's re.search, which the schema patterns assume.
        if (rule.TryGetProperty("pattern", out var pattern)
            && !Regex.IsMatch(text, pattern.GetString()!, RegexOptions.None, TimeSpan.FromSeconds(1)))
        {
            throw new SchemaViolation($"{location}: pattern mismatch");
        }

        if (rule.TryGetProperty("minLength", out var minLength) && text.Length < minLength.GetInt32())
        {
            throw new SchemaViolation($"{location}: string too short");
        }

        if (!rule.TryGetProperty("format", out var format))
        {
            return;
        }

        switch (format.GetString())
        {
            case "date-time" when !TryParseOffset(text, out _):
                throw new SchemaViolation($"{location}: invalid date-time");
            case "uri" when text.Length > 0 && !Uri.TryCreate(text, UriKind.Absolute, out _):
                throw new SchemaViolation($"{location}: invalid URI");
        }
    }

    private static void CheckNumber(JsonElement value, JsonElement rule, string location)
    {
        if (!IsInteger(value))
        {
            return;
        }

        var number = value.GetInt64();
        if (rule.TryGetProperty("minimum", out var minimum) && number < minimum.GetInt64())
        {
            throw new SchemaViolation($"{location}: number outside range");
        }

        if (rule.TryGetProperty("maximum", out var maximum) && number > maximum.GetInt64())
        {
            throw new SchemaViolation($"{location}: number outside range");
        }
    }

    /// <summary>
    /// Timezone-bearing ISO-8601 only. A naive timestamp is rejected, matching the
    /// producer's rule that every recorded instant is unambiguous.
    /// </summary>
    public static bool TryParseOffset(string text, out DateTimeOffset value) =>
        DateTimeOffset.TryParse(
            text,
            CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
            out value)
        && HasExplicitZone(text);

    private static bool HasExplicitZone(string text) =>
        text.EndsWith('Z') || text.EndsWith('z') || Regex.IsMatch(
            text, @"[+-]\d{2}:?\d{2}$", RegexOptions.None, TimeSpan.FromSeconds(1));

    private static bool SameJson(JsonElement left, JsonElement right) =>
        left.ValueKind == right.ValueKind
        && string.Equals(left.GetRawText(), right.GetRawText(), StringComparison.Ordinal);

    private static string Describe(JsonElement value) => value.GetRawText();
}
