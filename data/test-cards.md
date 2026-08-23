# Razorpay test-mode instruments

Transcribed from Razorpay's own docs source,
[razorpay/markdown-docs · payments/payments/test-card-details.md](https://github.com/razorpay/markdown-docs/blob/master/payments/payments/test-card-details.md),
retrieved 23 Aug 2026.

> **Do not substitute the generic `4111 1111 1111 1111`.** It is not in
> Razorpay's domestic set and fails with the misleading message
> *"International cards are not supported"*. See INCIDENTS.md #9.

## Domestic (Indian) — use these to mint

| Network | Number |
|---|---|
| Visa | `4100 2800 0000 1007` |
| Mastercard | `5500 6700 0000 1002` |
| RuPay | `6527 6589 0000 1005` |
| Diners | `3608 280009 1007` |
| Amex | `3402 560004 01007` |

**CVV** any random · **Expiry** any future date · **OTP** any 4–10 digits to
succeed, **under 4 digits to fail deliberately**.

## Error-scenario cards — the documented failure taxonomy

Twenty cards, each producing a specific documented failure. These are the source
of MILAAN's `failed payment` exception class: a failed payment never settles, so
it must not enter a candidate pool, and a pool polluted with them is a realistic
exception rather than an invented one. Using Razorpay's own failure modes means
these labels are not mine to be trusted about.

**Visa** `4100 2800 000X 000Y`:
`4100 2800 0009 0000`, `4100 2800 0008 0001`, `4100 2800 0007 0002`,
`4100 2800 0006 0003`, `4100 2800 0005 0004`, `4100 2800 0004 0005`,
`4100 2800 0003 0006`, `4100 2800 0002 0007`, `4100 2800 0001 0008`,
`4100 2800 0000 0009`

**Mastercard** `5305 6200 000X 000Y`:
`5305 6200 0009 0007`, `5305 6200 0008 0008`, `5305 6200 0007 0009`,
`5305 6200 0006 0000`, `5305 6200 0005 0001`, `5305 6200 0004 0002`,
`5305 6200 0003 0003`, `5305 6200 0002 0004`, `5305 6200 0001 0005`,
`5305 6200 0000 0006`

## International — not used by this project

`5555 5555 5555 4444`, `5105 1051 0510 5100`, `5104 0600 0000 0008` (Mastercard);
`4012 8888 8888 1881` (Visa). Disabled by default on new accounts.

## Subscriptions

| | |
|---|---|
| Visa (domestic) | `4718 6091 0820 4366` |
| Mastercard (intl credit) | `5104 0155 5555 5558` |
| Mastercard (intl debit) | `5104 0600 0000 0008` |

> **Card tokens are valid for 3 days only.** Any pre-minted subscription pool
> goes stale within the build window and must be re-minted before an eval run
> that depends on it.
