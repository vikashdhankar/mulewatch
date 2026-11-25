"""The label scheme, in one place. The Label Studio config, the models and the reports read it from here.

The seven post classes follow the categories the MuleWatch app already uses, plus the two
look-alike classes a classifier must not confuse with them (awareness posts and ordinary posts).
"""

CLASSES = [
    "mule_account_sale",          # selling or renting bank accounts / full kits (passbook + ATM + net banking + SIM)
    "account_holder_recruitment", # asking people to lend their own account for a commission
    "card_sale",                  # selling ATM / debit / credit cards or card details
    "kyc_fraud",                  # fake KYC, rented identity documents, accounts opened on others' papers
    "easy_money_lure",            # "earn daily from home" task / job offers that end in mule recruitment
    "awareness",                  # warnings, news or advice about mule accounts (must not be flagged)
    "benign",                     # everything else, including legitimate banking and financial posts
]

CLASS_DESCRIPTIONS = {
    "mule_account_sale": "Sells or rents bank accounts, current/savings accounts or full kits",
    "account_holder_recruitment": "Recruits people to hand over or 'rent' their own account for commission",
    "card_sale": "Sells ATM, debit or credit cards or card details",
    "kyc_fraud": "Offers fake KYC, rented identity documents or accounts opened on someone else's papers",
    "easy_money_lure": "Easy-money / task / part-time job offer that leads to account misuse",
    "awareness": "Warns about, reports on or explains mule-account fraud",
    "benign": "Unrelated, or a legitimate financial post",
}

# Span labels annotators mark inside the (already redacted) text.
SPAN_LABELS = ["price", "bank", "account_type", "contact", "upi"]

LANGUAGES = ["en", "hi", "hinglish", "mixed"]

SUSPICIOUS = [c for c in CLASSES if c not in ("awareness", "benign")]
