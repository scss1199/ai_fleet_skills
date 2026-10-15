/-!
ClaimContract.lean — the admission rule for the claim classes a reply may assert at the end of
a turn (operator 2026-10-13: 「f1s 藉由 LEAN / JEV 等架構直接杜絕任何可能的說謊與假裝」;
「說謊與推託的部分要嚴格處理與禁止」; 「嚴格禁止隨意產出 .md 和 .json」).

A claim class is admissible only against Evidence the PROOF Stop hook derived from the turn's
own transcript and the disk — never from anything the model wrote about itself. These theorems
are about the MODEL; `claim_conformance.py` is what binds them to the running hook
(`_skill/engines/claude-proof-hook.py`, function `admissible`) by comparing the full table.

Classes come from the 2026-10-13 audit of the ai_trader conversations
(ai_darkhero/evidence/ai-trader-conversation-audit-20261013/report.md):
  read          「已讀 / 已抓取 / read / fetched」      — 14 logged-out shells were reported as read
  progress      「本輪推進完成 / 有進展」               — housekeeping reported as progress 18 times
  automated     「已自動化 / 會自動跑」                 — the 09-21 pre-market check was never automated
  blocker       「做不到 / 會被拉回來 / cannot」        — a deletable obstacle presented as a constraint
  decision      「需要你決定：X」 repeated, or not the operator's — re-asked 12 / 27 / 50 times; F1SCore: only
                                                          an operator-reserved / data-loss decision may be asked
  askValue      「需要你的一個數字 / 請提供」           — asked for a fee already in the repo
  unrequestedFile a .md / .json written that no prompt asked for and no mechanism requires
  codeChange    code written or edited in a turn with no usage / existing-implementation search before it
  fixClaim      「修好 / 已修復 / fixed」 after a code write with no green test run after the LAST write
                — tdd skill (threads @nashlikeai 2026-10-14): 先寫測試再寫程式，避免改 A 壞 B
                — F1S ③ 先重用再自己寫 + Brownfield 「先全域搜尋」 (kyloren_bot cards cea9bf31, 89f0cb75)
  handback      「請你去跑 / 由你來做 / 你自己執行」    — 推託: a step handed to the operator that
                                                          was neither tried nor on a red line
-/
namespace Fames.ClaimContract

inductive ClaimClass
  | read | progress | automated | blocker | decision | askValue | unrequestedFile | handback | codeChange
  | fixClaim
  deriving DecidableEq, Repr

/-- Facts the hook derives from the turn (tool results, tool inputs, disk, git, session history). -/
structure Evidence where
  readResult : Bool          -- a successful read-type tool result exists in this turn
  namedTargetTouched : Bool  -- every path / URL the line names occurs in a tool input or result of this turn
  anchor : Bool              -- the line names an existing path, a commit git can resolve, or a number a tool printed
  schedulerFact : Bool       -- the line names a rider id in hosts.json / an existing path, or the turn touched the scheduler
  failureObserved : Bool     -- some tool call in this turn actually failed (or was denied)
  askedBefore : Bool         -- the same decision line was already asked earlier in this session
  searched : Bool            -- a grep / search tool call ran in this turn before asking
  requestedDoc : Bool        -- the prompt of this turn asked for that document / file
  redLineNamed : Bool        -- the line names an operator-reserved action (login/OAuth, permanent delete,
                             --   rider arming, global settings, secrets, funds)
  searchedBeforeWrite : Bool -- a grep / glob / find ran in this turn BEFORE the first code write
  testAfterWrite : Bool      -- a green test run happened AFTER the last code write of the turn
  deriving DecidableEq, Repr

/-- The admission rule. A line carrying an UNKNOWN / 未驗證 qualifier, or negating the claim, is not a
claim and never reaches this function. A hand-back is admissible only when the step is the operator's
by red line, or the model actually tried and a tool failed. -/
def admissible : ClaimClass → Evidence → Bool
  | .read, e => e.readResult && e.namedTargetTouched
  | .progress, e => e.anchor
  | .automated, e => e.schedulerFact
  | .blocker, e => e.failureObserved
  | .decision, e => !e.askedBefore && e.redLineNamed   -- a decision is the operator's only on a red line / data loss
  | .askValue, e => e.searched
  | .unrequestedFile, e => e.requestedDoc
  | .handback, e => e.redLineNamed || e.failureObserved
  | .codeChange, e => e.searchedBeforeWrite
  | .fixClaim, e => e.testAfterWrite

/-- The worst case: nothing observed, and the decision was already asked. -/
def noEvidence : Evidence :=
  { readResult := false, namedTargetTouched := false, anchor := false, schedulerFact := false,
    failureObserved := false, askedBefore := true, searched := false, requestedDoc := false,
    redLineNamed := false, searchedBeforeWrite := false, testAfterWrite := false }

/-- Evidence order: `b` knows at least what `a` knows (and `askedBefore` can only be cleared). -/
def atLeast (a b : Evidence) : Bool :=
  (!a.readResult || b.readResult) && (!a.namedTargetTouched || b.namedTargetTouched) &&
  (!a.anchor || b.anchor) && (!a.schedulerFact || b.schedulerFact) &&
  (!a.failureObserved || b.failureObserved) && (!b.askedBefore || a.askedBefore) &&
  (!a.searched || b.searched) && (!a.requestedDoc || b.requestedDoc) &&
  (!a.redLineNamed || b.redLineNamed) && (!a.searchedBeforeWrite || b.searchedBeforeWrite) &&
  (!a.testAfterWrite || b.testAfterWrite)

/-! ## Theorems (fail closed, one evidence kind per class, monotone in evidence) -/

theorem no_evidence_no_admission : ∀ c : ClaimClass, admissible c noEvidence = false := by
  intro c; cases c <;> rfl

theorem read_needs_read_result (e : Evidence) (h : e.readResult = false) :
    admissible .read e = false := by
  simp [admissible, h]

theorem read_needs_named_target (e : Evidence) (h : e.namedTargetTouched = false) :
    admissible .read e = false := by
  simp [admissible, h]

theorem progress_needs_anchor (e : Evidence) (h : e.anchor = false) :
    admissible .progress e = false := by
  simp [admissible, h]

theorem automated_needs_scheduler_fact (e : Evidence) (h : e.schedulerFact = false) :
    admissible .automated e = false := by
  simp [admissible, h]

theorem blocker_needs_observed_failure (e : Evidence) (h : e.failureObserved = false) :
    admissible .blocker e = false := by
  simp [admissible, h]

theorem repeated_decision_inadmissible (e : Evidence) (h : e.askedBefore = true) :
    admissible .decision e = false := by
  simp [admissible, h]

/-- 「需要你決定」 about something that is not the operator's (no red line, no data loss) is 推託. -/
theorem decision_needs_operator_authority (e : Evidence) (h : e.redLineNamed = false) :
    admissible .decision e = false := by
  simp [admissible, h]

theorem ask_value_needs_search (e : Evidence) (h : e.searched = false) :
    admissible .askValue e = false := by
  simp [admissible, h]

theorem unrequested_file_needs_request (e : Evidence) (h : e.requestedDoc = false) :
    admissible .unrequestedFile e = false := by
  simp [admissible, h]

/-- 推託 is inadmissible unless the step is operator-reserved or was really tried and failed. -/
theorem handback_needs_red_line_or_failure (e : Evidence) (h1 : e.redLineNamed = false)
    (h2 : e.failureObserved = false) : admissible .handback e = false := by
  simp [admissible, h1, h2]

/-- ③ 先重用再自己寫: a code change with no prior search is never admissible. -/
theorem code_change_needs_prior_search (e : Evidence) (h : e.searchedBeforeWrite = false) :
    admissible .codeChange e = false := by
  simp [admissible, h]

/-- tdd: 「修好」 after a code write is never admissible without a green test after the last write. -/
theorem fix_claim_needs_test_after_write (e : Evidence) (h : e.testAfterWrite = false) :
    admissible .fixClaim e = false := by
  simp [admissible, h]

/-- Every admissible claim rests on at least one evidence fact the hook derived (no class is
admissible for free). -/
theorem admissible_rests_on_evidence (c : ClaimClass) (e : Evidence)
    (h : admissible c e = true) :
    e.readResult = true ∨ e.anchor = true ∨ e.schedulerFact = true ∨ e.failureObserved = true ∨
    e.askedBefore = false ∨ e.searched = true ∨ e.requestedDoc = true ∨ e.redLineNamed = true ∨
    e.searchedBeforeWrite = true ∨ e.testAfterWrite = true := by
  cases c <;> simp [admissible] at h <;> first | simp [h] | (rcases h with h | h <;> simp [h])

/-- More evidence never turns an admissible claim into an inadmissible one. -/
theorem admissible_mono (c : ClaimClass) (a b : Evidence) (hab : atLeast a b = true)
    (ha : admissible c a = true) : admissible c b = true := by
  simp [atLeast] at hab
  cases c <;> simp [admissible] at ha ⊢ <;> first | simp_all | (rcases ha with ha | ha <;> simp_all)

/-! ## Table for the conformance runner -/

def bools : List Bool := [false, true]

def allEvidence : List Evidence :=
  bools.flatMap fun r => bools.flatMap fun n => bools.flatMap fun a => bools.flatMap fun s =>
  bools.flatMap fun f => bools.flatMap fun d => bools.flatMap fun q => bools.flatMap fun m =>
  bools.flatMap fun l => bools.flatMap fun w => bools.map fun t =>
    { readResult := r, namedTargetTouched := n, anchor := a, schedulerFact := s,
      failureObserved := f, askedBefore := d, searched := q, requestedDoc := m, redLineNamed := l,
      searchedBeforeWrite := w, testAfterWrite := t }

def classes : List ClaimClass :=
  [.read, .progress, .automated, .blocker, .decision, .askValue, .unrequestedFile, .handback, .codeChange,
   .fixClaim]

def bit (b : Bool) : String := if b then "1" else "0"

def key (e : Evidence) : String :=
  bit e.readResult ++ bit e.namedTargetTouched ++ bit e.anchor ++ bit e.schedulerFact ++
  bit e.failureObserved ++ bit e.askedBefore ++ bit e.searched ++ bit e.requestedDoc ++
  bit e.redLineNamed ++ bit e.searchedBeforeWrite ++ bit e.testAfterWrite

def className : ClaimClass → String
  | .read => "read" | .progress => "progress" | .automated => "automated" | .blocker => "blocker"
  | .decision => "decision" | .askValue => "ask_value" | .unrequestedFile => "unrequested_file"
  | .handback => "handback" | .codeChange => "code_change" | .fixClaim => "fix_claim"

/-- `<class>:<11 evidence bits>=<0|1>;...` over all 10 × 2048 cells. -/
def table : String :=
  String.intercalate ";" (classes.flatMap fun c => allEvidence.map fun e =>
    className c ++ ":" ++ key e ++ "=" ++ bit (admissible c e))

end Fames.ClaimContract
