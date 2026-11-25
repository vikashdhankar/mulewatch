"""Label Studio labelling config, generated from common/labels.py so the two never drift apart.

    python -m annotate.label_config > annotate/label_config.xml
"""
from xml.sax.saxutils import quoteattr

from common.labels import CLASS_DESCRIPTIONS, CLASSES, LANGUAGES, SPAN_LABELS

SPAN_COLOURS = {"price": "#f59e0b", "bank": "#3b82f6", "account_type": "#8b5cf6", "contact": "#ef4444",
                "upi": "#10b981"}
SPAN_HINTS = {
    "price": "an amount asked or offered (Rs 25,000, 2k, ₹1500 daily)",
    "bank": "a bank or payment app named (SBI, HDFC, Paytm)",
    "account_type": "kind of account or kit (current account, corporate kit, savings, firm account)",
    "contact": "how to reach the poster ([PHONE], [HANDLE], [URL], 'DM me', 'WhatsApp karo')",
    "upi": "a UPI ID placeholder [UPI] or words asking for UPI payment",
}


def build() -> str:
    def labels(name, to):
        rows = [f'  <Labels name="{name}" toName="{to}">']
        for s in SPAN_LABELS:
            rows.append(f'    <Label value="{s}" background="{SPAN_COLOURS[s]}" hint={quoteattr(SPAN_HINTS[s])}/>')
        rows.append("  </Labels>")
        return rows

    lines = ['<View>', '  <Header value="Post (identifiers are already masked)"/>']
    lines += labels("spans", "text")
    lines += ['  <Text name="text" value="$text" granularity="word"/>',
              '  <Header value="Text read from the image (OCR)" size="5"/>']
    lines += labels("ocr_spans", "ocr_text")
    lines += ['  <Text name="ocr_text" value="$ocr_text" granularity="word"/>',
              '  <Header value="Class"/>',
              '  <Choices name="label" toName="text" choice="single-radio" required="true" showInline="false">']
    for c in CLASSES:
        lines.append(f'    <Choice value="{c}" hint={quoteattr(CLASS_DESCRIPTIONS[c])}/>')
    lines += ['  </Choices>',
              '  <Header value="Language (pre-filled, correct it if wrong)" size="5"/>',
              '  <Choices name="language" toName="text" choice="single" showInline="true">']
    lines += [f'    <Choice value="{lang}"/>' for lang in LANGUAGES]
    lines += ['  </Choices>',
              '  <TextArea name="notes" toName="text" maxSubmissions="1" rows="2"'
              ' placeholder="Optional: why this was hard to label"/>',
              '</View>']
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(build(), end="")
