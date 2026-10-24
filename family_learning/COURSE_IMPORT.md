# AI-authored course files, version 1

Use the reusable context in the root README with any AI chat tool. The parent
chooses the subject, age/experience, interests, language, lesson count and goals.
Ask for one self-contained UTF-8 JSON file. This file-import path needs no provider
integration or credentials. The separate **Create course with AI** workflow can
use the parent's connected OpenAI account. Learner work stays local in both paths.

## Import and review

1. Sign in as a parent administrator at `/family-learning`.
2. Expand **Import an AI-prepared course** in **Prepare lessons**.
3. Select a JSON file or paste its raw contents; choose **Validate and review**.
4. Read every exercise and private answer key. Check facts, difficulty, hints,
   requirements, starter code and expected output. Imported text is displayed
   as text, never HTML, executable instructions or automatically fetched links.
5. Check the review acknowledgement and **Publish reviewed course**.
6. Assign the saved course to an enrolled learner separately.

Preview writes no course or progress records and executes no program. Publishing
revalidates the document and saves a parent-owned immutable course. Importing
the identical content again as the same parent reuses that course; changing it
creates a separate course and does not overwrite existing work. Cancel or edit
the JSON to discard a preview. Editing clears the review acknowledgement.
The learner cannot call either import endpoint. Unknown or locked courses stay
inaccessible under the normal assignment/unlock rules.

## Envelope and common fields

The top-level fields must be exactly `format`, `version`, and `course`:

| Field | Value or limit |
| --- | --- |
| `format` | Exactly `family-learning-course` |
| `version` | Integer `1` |
| `course` | Object with exactly `title`, `subject`, `objectives`, `lessons` |
| `title`, `subject` | Nonempty strings, up to 200 characters each |
| `objectives` | 1–20 nonempty strings, up to 500 characters each |
| `lessons` | 1–100 exercise objects in unlock order |

Maximum file size is 1,000,000 bytes. No Markdown fences, comments, duplicate
JSON keys, NaN/Infinity, extra metadata, account IDs or assignment instructions.
A UTF-8 byte-order mark is accepted. See [example-course.json](example-course.json)
for a complete valid two-exercise Python course.

Every exercise requires:

| Field | Value or limit |
| --- | --- |
| `id` | Unique within the course; 1–64 lowercase letters, digits or hyphens |
| `title`, `explanation`, `question`, `success` | Nonempty strings, up to 20,000 characters each |
| `kind` | `python`, `choice`, `number` or `writing` |
| `hints` | 0–10 nonempty strings, up to 2,000 characters each |

Use short explanations, concrete questions, progressive hints and descriptive
success feedback. A hint can be requested before a coding attempt. No automatic
AI-generated feedback is used while the child works.

## Exercise-specific fields

| Kind | Additional fields |
| --- | --- |
| `python` | Required `expected_output`: string, up to 8,192 bytes. Optional `starter_code`: string, up to 16,384 bytes; optional `requirements`: list containing only `assignment`, `for_loop`, `while_loop`. No `answer`, `choices` or `rubric`. |
| `choice` | `choices`: 2–8 nonempty strings, up to 1,000 characters each. `answer`: integer index starting at **0**. |
| `number` | `answer`: finite decimal **string**, up to 100 characters, e.g. `"3.5"`. |
| `writing` | `rubric`: 1–20 nonempty criteria, up to 1,000 characters each. No `answer`; a parent reviews the submission. |

Only Python exercises may have `starter_code`, `expected_output` or
`requirements`. Keep fields relevant to the chosen kind. Courses can mix kinds.

Python supports variables, arithmetic, comparisons, conditionals, for/while
loops, lists/tuples, subscripts, break/continue/pass, and calls to `print`,
`range`, `len`, `str`, `int`, `float`, `round`, `min`, `max`, `sum`, `abs`.
No imports, functions/classes, attribute access, method calls, keyword arguments,
f-strings, input prompts, file/network operations or third-party packages.
Use ordinary names without leading underscores. Do not overwrite built-in names.
Starter programs must parse and fit this subset; validation never runs them.

Expected output is checked against actual printed output, normalizing CRLF and
trailing newlines only. Spaces and intermediate newlines matter. Requirements
check for the named syntax in the submitted program; they do not establish
mastery. Runtime isolation and resource limits remain enforced separately.

## Troubleshooting

Give your AI tool the validation error plus these format rules, then ask it to
return the complete corrected JSON. Do not ask it to bypass validation or widen
runner permissions. For unsupported Python constructs, simplify the exercise
to the supported subset. Review revised output before publishing again.
The application does not automatically test a generated answer against every
exercise. Try the course through a learner account before using it for study.
