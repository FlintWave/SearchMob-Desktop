## ADDED Requirements

### Requirement: Ten-language UI through a runtime catalog with English fallback

The system SHALL translate every user-facing interface string into the active locale through a
runtime catalog keyed by the English source string. The system SHALL ship ten locales — English plus
Chinese (Simplified), Hindi, Spanish, Arabic, French, Bengali, Portuguese, Indonesian, and Urdu — and
SHALL render the English source string itself when the active locale has no translation for it, so a
missing entry never shows a placeholder key.

#### Scenario: A translated string renders in the active locale

- **WHEN** the active locale is Spanish and the interface shows the source string "Search the web"
- **THEN** the Spanish translation is rendered

#### Scenario: A missing translation falls back to English

- **WHEN** the active locale has no entry for a given English source string
- **THEN** the English source string is rendered unchanged rather than a missing-key marker

### Requirement: Plural and context-disambiguated translations

The system SHALL select the correct plural form for a counted string using the locale's CLDR plural
categories, supporting locales from two categories (English, Spanish) through six (Arabic). The
system SHALL also disambiguate two identical English source strings that translate differently by an
explicit context label.

#### Scenario: A count selects the locale's plural form

- **WHEN** a counted string is rendered for a count of 1 and again for a count of 5 in a locale whose
  one and other forms differ
- **THEN** each count renders the form its CLDR category requires for that locale

#### Scenario: Context disambiguates identical English strings

- **WHEN** two interface strings share the same English spelling but carry different context labels
- **THEN** each renders its own locale translation for that context

### Requirement: Right-to-left layout for right-to-left languages

The system SHALL lay the interface out right-to-left when the active locale is written right-to-left
(Arabic, Urdu) and left-to-right otherwise, on both the desktop interface and the served page. The
served page SHALL set the document language attribute for every locale and the direction attribute to
`rtl` for right-to-left locales.

#### Scenario: An Arabic served page is right-to-left

- **WHEN** the served page is rendered in Arabic
- **THEN** the document declares Arabic as its language and right-to-left direction, and the interface
  chrome is mirrored while a Latin-script query inside it stays left-to-right

#### Scenario: Switching the desktop language flips direction live

- **WHEN** the desktop interface is switched from English to Arabic and then to Chinese
- **THEN** the layout direction becomes right-to-left for Arabic and left-to-right for Chinese without
  restarting the application

### Requirement: Persisted language choice that follows the OS by default

The system SHALL let the user choose the interface language and SHALL remember that choice across
sessions. When no choice has been made, the system SHALL follow the operating system's language if it
is one of the shipped locales, otherwise English. Choosing to follow the system SHALL clear the saved
language so the OS locale applies again.

#### Scenario: First launch follows the OS language

- **WHEN** the application starts with no saved language and the OS locale is a shipped locale
- **THEN** the interface starts in that OS locale

#### Scenario: A saved choice persists across restarts

- **WHEN** the user selects a language and restarts the application
- **THEN** the interface starts in the selected language regardless of the OS locale

### Requirement: Per-request locale on the served page

The served page SHALL resolve the language for each request independently, in precedence order: the
owner's saved language, then the visitor's `Accept-Language` (first supported entry), then the
server's OS locale, then English. A request's locale SHALL NOT affect the desktop interface's active
language or any other request.

#### Scenario: A visitor's Accept-Language is honoured when no language is pinned

- **WHEN** the owner has not pinned a language and a visitor requests the page with an
  `Accept-Language` naming a shipped locale first
- **THEN** the page renders in that locale

#### Scenario: A pinned language overrides the visitor header

- **WHEN** the owner has pinned a language and a visitor sends a different `Accept-Language`
- **THEN** the page renders in the owner's pinned language

### Requirement: Result tailoring through per-engine language and region parameters

The system SHALL tailor result requests to the active non-English locale by passing each capable
engine its documented language/region parameters (DuckDuckGo a region-language code; Brave a search
language, country, and UI language). For the English locale, and for any locale an engine has no code
for, the system SHALL omit those parameters and request results region-neutrally, exactly as before
this change. Engines that document no such parameter SHALL be left unchanged. This tailoring SHALL
affect only the request, not how results are ranked or filtered.

#### Scenario: A non-English locale tailors the engine request

- **WHEN** a search runs with the active locale set to Spanish
- **THEN** the capable engines receive their Spanish language/region parameters and engines without
  such a parameter are unchanged

#### Scenario: English stays region-neutral

- **WHEN** a search runs with the active locale set to English
- **THEN** no language/region parameters are added and the request is identical to the pre-change
  region-neutral request
