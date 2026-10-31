/-!
# FAMES decision kernel

A finite, total model of the decision rules the FAMES gates enforce in code, with the properties the
fleet relies on proved as theorems. Core Lean only (no Mathlib), so one check takes seconds.

Each section mirrors running Python. The mirror is never assumed: `_lean/fames/conformance.py`
evaluates the tables at the bottom of this file with Lean and compares them with the real functions.

  * section 1  `_skill/fleet-skills/fames/scripts/fames_fleet.py :: validate_run`
               (phase ledger, SCF residual vector, AEX activation gate)
  * section 2  `_skill/engines/claude-claim-integrity-hook.py :: lint_message, evaluate_hook`
               (claim state, gate verdict, block / hard-stop action)
  * section 3  `fames_fleet.py :: validate_autonomic` (authority may only narrow)
  * section 4  `_lean/fames/lean_gate.py :: evidence_ok` (what counts as mathematical evidence)

A theorem here is a statement about THIS MODEL. It reaches the Python only through the conformance
receipt, and only over the finite abstract domain enumerated in section 5.
-/

namespace Fames

/-! ## 1. Phase ledger, residual vector, AEX gate -/

/-- The `phase` cell of a ledger row. `other` is any value that is not one of the five names. -/
inductive Phase where
  | FP | MTM | SCF | AEX | SEAL | other
  deriving DecidableEq, Repr

def executionOrder : List Phase := [.FP, .MTM, .SCF, .AEX, .SEAL]

/-- The `state` cell. `invalid` is a missing cell or a word outside the four legal ones. -/
inductive PState where
  | pass | notApplicable | unknown | fail | invalid
  deriving DecidableEq, Repr

/-- The `activation_predicate` cell: the JSON literal true, the literal false, or anything else. -/
inductive Pred where
  | isTrue | isFalse | other
  deriving DecidableEq, Repr

/-- The cells of one ledger row the validator reads. `hasWhy` is a truthy `why`; `targetNamed` is a
`target_residual` that names one of the seven residual keys. -/
structure Row where
  state : PState
  pred : Pred
  hasWhy : Bool
  targetNamed : Bool
  deriving DecidableEq, Repr

/-- What the validator reads for a phase that has no row. -/
def Row.missing : Row := ⟨.invalid, .other, false, false⟩

inductive RowError where
  | invalidState | failsClosed | naUnjustified
  deriving DecidableEq, Repr

def rowError (r : Row) : Option RowError :=
  match r.state with
  | .pass => none
  | .notApplicable => if r.pred = .isFalse ∧ r.hasWhy = true then none else some .naUnjustified
  | .unknown => some .failsClosed
  | .fail => some .failsClosed
  | .invalid => some .invalidState

/-- One residual cell: compares equal to 0, any other value, or JSON null. -/
inductive RVal where
  | zero | nonzero | null
  deriving DecidableEq, Repr

/-- A residual vector. `complete = false` means at least one of the seven keys is absent. -/
structure Residual where
  complete : Bool
  outcome : RVal
  safety : RVal
  evidence : RVal
  complexity : RVal
  portability : RVal
  authority : RVal
  operability : RVal
  deriving DecidableEq, Repr

/-- What the validator reads when the SCF row is missing or carries no residual object. -/
def Residual.absent : Residual := ⟨false, .null, .null, .null, .null, .null, .null, .null⟩

/-- An incomplete vector is replaced by the empty one, so every key reads null. -/
def Residual.read (r : Residual) (v : RVal) : RVal := if r.complete then v else .null

def Residual.comparable (r : Residual) : Bool :=
  [r.outcome, r.safety, r.evidence, r.complexity, r.portability, r.authority, r.operability].any
    fun v => r.read v == .nonzero

/-- One ledger row: its phase tag, its cells, and its `residual` object when it has one. -/
structure Entry where
  phase : Phase
  row : Row
  residual : Option Residual
  deriving DecidableEq, Repr

inductive HardKey where
  | safety | evidence | authority
  deriving DecidableEq, Repr

inductive Err where
  | order
  | row (p : Phase) (e : RowError)
  | residualIncomplete
  | notConverged (k : HardKey)
  | aexMustActivate
  | aexMustNameTarget
  | aexMustNotActivate
  deriving DecidableEq, Repr

structure Run where
  ledger : List Entry
  crossCycle : Bool
  deriving DecidableEq, Repr

/-- `phase_map` is a dictionary built in ledger order, so the last row of a phase wins. -/
def lookupEntry (p : Phase) (ledger : List Entry) : Option Entry :=
  ledger.reverse.find? fun e => e.phase == p

def lookup (p : Phase) (ledger : List Entry) : Row :=
  match lookupEntry p ledger with
  | some e => e.row
  | none => Row.missing

/-- The residual the validator reads: the one on the SCF row that won. -/
def scfResidual (ledger : List Entry) : Residual :=
  match lookupEntry .SCF ledger with
  | some e => e.residual.getD Residual.absent
  | none => Residual.absent

def orderErrors (run : Run) : List Err :=
  if run.ledger.map (fun e => e.phase) = executionOrder then [] else [.order]

def rowErr (run : Run) (p : Phase) : List Err :=
  match rowError (lookup p run.ledger) with
  | none => []
  | some e => [.row p e]

def rowErrors (run : Run) : List Err :=
  rowErr run .FP ++ rowErr run .MTM ++ rowErr run .SCF ++ rowErr run .AEX ++ rowErr run .SEAL

def hardErr (r : Residual) (v : RVal) (k : HardKey) : List Err :=
  if r.read v = .zero then [] else [.notConverged k]

def residualErrors (r : Residual) : List Err :=
  (if r.complete then [] else [.residualIncomplete]) ++ hardErr r r.safety .safety
    ++ hardErr r r.evidence .evidence ++ hardErr r r.authority .authority

def aexErrorsCore (aex : Row) (required : Bool) : List Err :=
  if required then
    if aex.state = .pass ∧ aex.pred = .isTrue then
      if aex.targetNamed then [] else [.aexMustNameTarget]
    else [.aexMustActivate]
  else
    if aex.state = .notApplicable ∧ aex.pred = .isFalse then [] else [.aexMustNotActivate]

def aexRequired (run : Run) : Bool := run.crossCycle && (scfResidual run.ledger).comparable

def aexErrors (run : Run) : List Err := aexErrorsCore (lookup .AEX run.ledger) (aexRequired run)

def runErrors (run : Run) : List Err :=
  orderErrors run ++ rowErrors run ++ residualErrors (scfResidual run.ledger) ++ aexErrors run

def runOk (run : Run) : Bool := (runErrors run).isEmpty

/-! ### Theorems about the ledger -/

theorem rowError_none_iff (r : Row) :
    rowError r = none ↔
      r.state = .pass ∨ (r.state = .notApplicable ∧ r.pred = .isFalse ∧ r.hasWhy = true) := by
  cases r with
  | mk s p w t => cases s <;> cases p <;> cases w <;> cases t <;> decide

theorem rowErr_nil_iff (run : Run) (p : Phase) :
    rowErr run p = [] ↔ rowError (lookup p run.ledger) = none := by
  unfold rowErr
  cases rowError (lookup p run.ledger) <;> simp

theorem residualErrors_nil_iff (r : Residual) :
    residualErrors r = [] ↔
      r.complete = true ∧ r.safety = .zero ∧ r.evidence = .zero ∧ r.authority = .zero := by
  cases r with
  | mk c o s e x p a q =>
    cases c <;> cases s <;> cases e <;> cases a <;> simp [residualErrors, hardErr, Residual.read]

theorem aexErrorsCore_nil_iff (aex : Row) (required : Bool) :
    aexErrorsCore aex required = [] ↔
      (required = true ∧ aex.state = .pass ∧ aex.pred = .isTrue ∧ aex.targetNamed = true) ∨
      (required = false ∧ aex.state = .notApplicable ∧ aex.pred = .isFalse) := by
  cases aex with
  | mk s p w t =>
    cases s <;> cases p <;> cases w <;> cases t <;> cases required <;> decide

theorem runOk_iff (run : Run) :
    runOk run = true ↔
      orderErrors run = [] ∧ rowErrors run = [] ∧ residualErrors (scfResidual run.ledger) = [] ∧
        aexErrors run = [] := by
  simp [runOk, runErrors]

/-- A passing run lists exactly FP, MTM, SCF, AEX, SEAL, in that order. -/
theorem ok_implies_order (run : Run) (h : runOk run = true) :
    run.ledger.map (fun e => e.phase) = executionOrder := by
  have h1 := ((runOk_iff run).1 h).1
  unfold orderErrors at h1
  split at h1
  · assumption
  · simp at h1

/-- In a passing run every phase is PASS, or NOT_APPLICABLE with a false predicate and a reason. -/
theorem ok_implies_rows_justified (run : Run) (h : runOk run = true) (p : Phase)
    (hp : p ∈ executionOrder) :
    (lookup p run.ledger).state = .pass ∨
      ((lookup p run.ledger).state = .notApplicable ∧ (lookup p run.ledger).pred = .isFalse ∧
        (lookup p run.ledger).hasWhy = true) := by
  have h2 := ((runOk_iff run).1 h).2.1
  simp only [rowErrors, List.append_eq_nil_iff] at h2
  obtain ⟨⟨⟨⟨hFP, hMTM⟩, hSCF⟩, hAEX⟩, hSEAL⟩ := h2
  simp only [executionOrder, List.mem_cons, List.not_mem_nil, or_false] at hp
  rcases hp with rfl | rfl | rfl | rfl | rfl
  · exact (rowError_none_iff _).1 ((rowErr_nil_iff run _).1 hFP)
  · exact (rowError_none_iff _).1 ((rowErr_nil_iff run _).1 hMTM)
  · exact (rowError_none_iff _).1 ((rowErr_nil_iff run _).1 hSCF)
  · exact (rowError_none_iff _).1 ((rowErr_nil_iff run _).1 hAEX)
  · exact (rowError_none_iff _).1 ((rowErr_nil_iff run _).1 hSEAL)

/-- UNKNOWN or FAIL in any of the five phases fails the run, whatever every other cell says. -/
theorem fail_closed (run : Run) (p : Phase) (hp : p ∈ executionOrder)
    (h : (lookup p run.ledger).state = .unknown ∨ (lookup p run.ledger).state = .fail) :
    runOk run = false := by
  cases hok : runOk run with
  | false => rfl
  | true =>
    have hrow := ok_implies_rows_justified run hok p hp
    rcases h with h | h <;> rcases hrow with h' | ⟨h', _⟩ <;> rw [h] at h' <;> cases h'

/-- A phase with no row, or with a state outside the four legal words, fails the run. -/
theorem invalid_state_fails (run : Run) (p : Phase) (hp : p ∈ executionOrder)
    (h : (lookup p run.ledger).state = .invalid) : runOk run = false := by
  cases hok : runOk run with
  | false => rfl
  | true =>
    have hrow := ok_implies_rows_justified run hok p hp
    rcases hrow with h' | ⟨h', _⟩ <;> rw [h] at h' <;> cases h'

/-- The three hard residuals are not compensable: no value of any other cell makes a run pass
while safety, evidence or authority is unconverged, null or absent. -/
theorem hard_residuals_non_compensable (run : Run) (h : runOk run = true) :
    (scfResidual run.ledger).complete = true ∧ (scfResidual run.ledger).safety = .zero ∧
      (scfResidual run.ledger).evidence = .zero ∧ (scfResidual run.ledger).authority = .zero :=
  (residualErrors_nil_iff _).1 ((runOk_iff run).1 h).2.2.1

/-- In a passing run AEX is active exactly when the horizon is cross-cycle and a residual is comparable. -/
theorem aex_activation_iff (run : Run) (h : runOk run = true) :
    (lookup .AEX run.ledger).state = .pass ↔
      (run.crossCycle = true ∧ (scfResidual run.ledger).comparable = true) := by
  have h4 := (aexErrorsCore_nil_iff _ _).1 ((runOk_iff run).1 h).2.2.2
  have hreq : aexRequired run = true ↔
      (run.crossCycle = true ∧ (scfResidual run.ledger).comparable = true) := by
    simp [aexRequired]
  rcases h4 with ⟨hr, hs, _, _⟩ | ⟨hr, hs, _⟩
  · exact ⟨fun _ => hreq.1 hr, fun _ => hs⟩
  · constructor
    · intro hpass
      rw [hs] at hpass
      cases hpass
    · intro hx
      rw [hreq.2 hx] at hr
      cases hr

/-- An active AEX names the residual it targets. -/
theorem aex_names_its_target (run : Run) (h : runOk run = true)
    (hp : (lookup .AEX run.ledger).state = .pass) : (lookup .AEX run.ledger).targetNamed = true := by
  have h4 := (aexErrorsCore_nil_iff _ _).1 ((runOk_iff run).1 h).2.2.2
  rcases h4 with ⟨_, _, _, ht⟩ | ⟨_, hs, _⟩
  · exact ht
  · rw [hs] at hp
    cases hp

/-! ## 2. Claim-integrity gate -/

inductive ClaimState where
  | supported | unknown | unsupported
  deriving DecidableEq, Repr

/-- UNKNOWN wording excuses a claim, except an efficiency claim; otherwise evidence decides. -/
def claimState (unknownWorded efficiencyRequired measured : Bool) : ClaimState :=
  if unknownWorded && !efficiencyRequired then .unknown
  else if measured then .supported else .unsupported

inductive Event where
  | stop | subagentStop | other
  deriving DecidableEq, Repr

def gateOkCore (event : Event) (hasInput hasUnsupported hasSupported lifecyclePass : Bool) : Bool :=
  match event with
  | .other => true
  | .subagentStop => hasInput && !hasUnsupported
  | .stop => hasInput && !hasUnsupported && lifecyclePass

structure GateInput where
  event : Event
  hasInput : Bool
  claims : List ClaimState
  lifecyclePass : Bool
  deriving DecidableEq, Repr

def gateOk (g : GateInput) : Bool :=
  gateOkCore g.event g.hasInput (g.claims.any fun c => c == .unsupported)
    (g.claims.any fun c => c == .supported) g.lifecyclePass

inductive Action where
  | allow | block | hardStop
  deriving DecidableEq, Repr

def maxBlocks : Nat := 3

def action (ok : Bool) (priorBlocks : Nat) (stopHookActive : Bool) : Action :=
  if ok then .allow
  else if maxBlocks ≤ priorBlocks + 1 ∧ stopHookActive = true then .hardStop
  else .block

theorem supported_needs_measurement (u e m : Bool) (h : claimState u e m = .supported) : m = true := by
  cases u <;> cases e <;> cases m <;> first | rfl | cases h

theorem efficiency_never_excused_by_unknown (u : Bool) : claimState u true false = .unsupported := by
  cases u <;> rfl

theorem unknown_wording_is_unknown (m : Bool) : claimState true false m = .unknown := by
  cases m <;> rfl

theorem gateOkCore_unsupported (e : Event) (i s l : Bool) (he : e ≠ .other) :
    gateOkCore e i true s l = false := by
  cases e <;> cases i <;> cases s <;> cases l <;> first | rfl | exact absurd rfl he

/-- One unsupported claim in a Stop or SubagentStop message blocks it. -/
theorem unsupported_claim_blocks (g : GateInput) (he : g.event ≠ .other)
    (hm : ClaimState.unsupported ∈ g.claims) : gateOk g = false := by
  have hany : (g.claims.any fun c => c == .unsupported) = true :=
    List.any_eq_true.2 ⟨_, hm, by decide⟩
  unfold gateOk
  rw [hany]
  exact gateOkCore_unsupported _ _ _ _ he

/-- A Stop event without a session id or a message is blocked: no input, no verdict. -/
theorem missing_input_blocks (g : GateInput) (he : g.event ≠ .other) (hi : g.hasInput = false) :
    gateOk g = false := by
  unfold gateOk
  rw [hi]
  cases hev : g.event with
  | other => exact absurd hev he
  | stop => rfl
  | subagentStop => rfl

/-- Every Stop needs the current FAMES turn lifecycle, including plain or UNKNOWN status. -/
theorem lifecycle_required_for_every_stop (g : GateInput) (he : g.event = .stop)
    (hl : g.lifecyclePass = false) : gateOk g = false := by
  simp [gateOk, gateOkCore, he, hl]

/-- A supported claim at Stop needs a passing FAMES turn lifecycle. -/
theorem lifecycle_required_for_supported (g : GateInput) (he : g.event = .stop)
    (hm : ClaimState.supported ∈ g.claims) (hl : g.lifecyclePass = false) : gateOk g = false := by
  exact lifecycle_required_for_every_stop g he hl

theorem allow_iff_ok (ok : Bool) (prior : Nat) (active : Bool) :
    action ok prior active = .allow ↔ ok = true := by
  cases ok <;> simp [action] <;> split <;> simp

/-- The gate gives up (hard stop) only after three consecutive blocks inside an active stop hook. -/
theorem hard_stop_needs_three_blocks (ok : Bool) (prior : Nat) (active : Bool)
    (h : action ok prior active = .hardStop) : ok = false ∧ maxBlocks ≤ prior + 1 ∧ active = true := by
  cases ok with
  | true => simp [action] at h
  | false =>
    have hfalse : action false prior active =
        if maxBlocks ≤ prior + 1 ∧ active = true then Action.hardStop else Action.block := rfl
    rw [hfalse] at h
    split at h
    · rename_i hc
      exact ⟨rfl, hc.1, hc.2⟩
    · cases h

/-! ## 3. Authority may only narrow -/

def authoritySubset (before after : List Nat) : Bool := after.all fun a => before.contains a

theorem authority_subset_sound (before after : List Nat) (h : authoritySubset before after = true) :
    ∀ x, x ∈ after → x ∈ before := by
  intro x hx
  have := List.all_eq_true.1 h x hx
  simpa using this

/-- No chain of individually valid steps widens authority. -/
theorem authority_subset_trans (a b c : List Nat) (hab : authoritySubset a b = true)
    (hbc : authoritySubset b c = true) : authoritySubset a c = true := by
  apply List.all_eq_true.2
  intro x hx
  have hb := authority_subset_sound b c hbc x hx
  have ha := authority_subset_sound a b hab x hb
  simpa using ha

/-- Dropping scopes is always a valid step. -/
theorem narrowing_never_expands (keep : Nat → Bool) (auth : List Nat) :
    authoritySubset auth (auth.filter keep) = true := by
  apply List.all_eq_true.2
  intro x hx
  have : x ∈ auth := (List.mem_filter.1 hx).1
  simpa using this

/-! ## 4. Mathematical evidence -/

/-- leanctl verdict classes: PROVED; CHECKED (clean run, nothing stated); any verdict that rejects
the source; nothing was checked. -/
inductive Verdict where
  | proved | checked | rejected | error
  deriving DecidableEq, Repr

/-- What the gate's own re-run of Lean said about the same source bytes: it agreed, it disagreed, it
has not run yet, or Lean cannot be run here. -/
inductive Replay where
  | agrees | disagrees | pending | unavailable
  deriving DecidableEq, Repr

structure MathEvidence where
  receiptIntact : Bool
  sourceIntact : Bool
  checkerCurrent : Bool
  verdict : Verdict
  theoremStated : Bool
  replay : Replay
  deriving DecidableEq, Repr

def mathOk (e : MathEvidence) : Bool :=
  e.receiptIntact && e.sourceIntact && e.checkerCurrent && e.verdict == .proved && e.theoremStated
    && e.replay == .agrees

/-- Only a PROVED verdict for a theorem the caller stated, on intact bytes, by the installed checker,
and only once the gate's own Lean run has agreed. -/
theorem math_needs_proved (e : MathEvidence) (h : mathOk e = true) :
    e.verdict = .proved ∧ e.theoremStated = true ∧ e.receiptIntact = true ∧ e.sourceIntact = true ∧
      e.checkerCurrent = true ∧ e.replay = .agrees := by
  cases e with
  | mk a b c v t r =>
    cases a <;> cases b <;> cases c <;> cases v <;> cases t <;> cases r <;>
      first | (exact ⟨rfl, rfl, rfl, rfl, rfl, rfl⟩) | (cases h)

/-- A receipt nobody has replayed yet proves nothing: waiting is not agreement. -/
theorem pending_replay_rejects (e : MathEvidence) (h : e.replay = .pending) : mathOk e = false := by
  cases e with
  | mk a b c v t r =>
    cases h
    cases a <;> cases b <;> cases c <;> cases v <;> cases t <;> rfl

/-- A receipt the gate's own Lean run contradicts is rejected, whatever the receipt says. -/
theorem replay_disagreement_rejects (e : MathEvidence) (h : e.replay = .disagrees) : mathOk e = false := by
  cases e with
  | mk a b c v t r =>
    cases h
    cases a <;> cases b <;> cases c <;> cases v <;> cases t <;> rfl

/-- Where Lean cannot be run the claim stays unproved: no checker, no theorem. -/
theorem no_lean_no_claim (e : MathEvidence) (h : e.replay = .unavailable) : mathOk e = false := by
  cases e with
  | mk a b c v t r =>
    cases h
    cases a <;> cases b <;> cases c <;> cases v <;> cases t <;> rfl

/-! ## 5. The finite domain the conformance run covers -/

def allBools : List Bool := [true, false]
def allPhases : List Phase := [.FP, .MTM, .SCF, .AEX, .SEAL, .other]
def allPStates : List PState := [.pass, .notApplicable, .unknown, .fail, .invalid]
def allPreds : List Pred := [.isTrue, .isFalse, .other]
def allRVals : List RVal := [.zero, .nonzero, .null]
def allClaimStates : List ClaimState := [.supported, .unknown, .unsupported]
def allEvents : List Event := [.stop, .subagentStop, .other]
def allVerdicts : List Verdict := [.proved, .checked, .rejected, .error]
def allReplays : List Replay := [.agrees, .disagrees, .pending, .unavailable]

def allRows : List Row :=
  allPStates.flatMap fun s => allPreds.flatMap fun p => allBools.flatMap fun w => allBools.map fun t =>
    ⟨s, p, w, t⟩

def allResiduals : List Residual :=
  allBools.flatMap fun c => allRVals.flatMap fun o => allRVals.flatMap fun s => allRVals.flatMap fun e =>
    allRVals.flatMap fun x => allRVals.flatMap fun p => allRVals.flatMap fun a => allRVals.map fun q =>
      ⟨c, o, s, e, x, p, a, q⟩

def allMathEvidence : List MathEvidence :=
  allBools.flatMap fun a => allBools.flatMap fun b => allBools.flatMap fun c => allVerdicts.flatMap fun v =>
    allBools.flatMap fun t => allReplays.map fun r => ⟨a, b, c, v, t, r⟩

theorem allBools_complete (b : Bool) : b ∈ allBools := by cases b <;> decide
theorem allRVals_complete (v : RVal) : v ∈ allRVals := by cases v <;> decide
theorem allVerdicts_complete (v : Verdict) : v ∈ allVerdicts := by cases v <;> decide
theorem allReplays_complete (r : Replay) : r ∈ allReplays := by cases r <;> decide

/-- The row table leaves no row out. -/
theorem allRows_complete (r : Row) : r ∈ allRows := by
  cases r with
  | mk s p w t => cases s <;> cases p <;> cases w <;> cases t <;> decide

/-- The residual table leaves no residual vector out. -/
theorem allResiduals_complete (r : Residual) : r ∈ allResiduals := by
  cases r with
  | mk c o s e x p a q =>
    simp only [allResiduals, List.mem_flatMap, List.mem_map]
    exact ⟨c, allBools_complete c, o, allRVals_complete o, s, allRVals_complete s, e, allRVals_complete e,
      x, allRVals_complete x, p, allRVals_complete p, a, allRVals_complete a, q, allRVals_complete q, rfl⟩

/-- The evidence table leaves no evidence record out. -/
theorem allMathEvidence_complete (e : MathEvidence) : e ∈ allMathEvidence := by
  cases e with
  | mk a b c v t r =>
    simp only [allMathEvidence, List.mem_flatMap, List.mem_map]
    exact ⟨a, allBools_complete a, b, allBools_complete b, c, allBools_complete c, v, allVerdicts_complete v,
      t, allBools_complete t, r, allReplays_complete r, rfl⟩

/-! ### Composite run domains -/

def baselineRow : Row := ⟨.pass, .other, false, false⟩
def baselineAex : Row := ⟨.notApplicable, .isFalse, true, false⟩
def activatedAex : Row := ⟨.pass, .isTrue, true, true⟩
def baselineResidual : Residual := ⟨true, .zero, .zero, .zero, .zero, .zero, .zero, .zero⟩

def entryFor (p : Phase) : Entry :=
  ⟨p, if p = .AEX then baselineAex else baselineRow, if p = .SCF then some baselineResidual else none⟩

def ledgerOf (col : List Phase) : List Entry := col.map entryFor
def baselineLedger : List Entry := ledgerOf executionOrder
def baselineRun : Run := ⟨baselineLedger, false⟩

def setRow (p : Phase) (r : Row) (ledger : List Entry) : List Entry :=
  ledger.map fun e => if e.phase = p then { e with row := r } else e

def setResidual (res : Option Residual) (ledger : List Entry) : List Entry :=
  ledger.map fun e => if e.phase = .SCF then { e with residual := res } else e

theorem baseline_passes : runOk baselineRun = true := by decide

/-- A: every row value in every phase, both horizons. -/
def domainRows : List Run :=
  allBools.flatMap fun x => executionOrder.flatMap fun p => allRows.map fun r =>
    ⟨setRow p r baselineLedger, x⟩

def residualClasses : List (Option Residual) :=
  [some baselineResidual, some { baselineResidual with outcome := .nonzero },
   some { baselineResidual with operability := .nonzero }, some { baselineResidual with safety := .nonzero },
   some { baselineResidual with complexity := .null },
   some { baselineResidual with complete := false, outcome := .nonzero }, none]

/-- B: the AEX gate: horizon x residual class x every AEX row. -/
def domainAex : List Run :=
  allBools.flatMap fun x => residualClasses.flatMap fun res => allRows.map fun r =>
    ⟨setResidual res (setRow .AEX r baselineLedger), x⟩

/-- C: every residual vector (and none), both horizons, AEX at rest and activated. -/
def domainResidual : List Run :=
  allBools.flatMap fun x => (none :: allResiduals.map some).flatMap fun res =>
    [⟨setResidual res baselineLedger, x⟩, ⟨setResidual res (setRow .AEX activatedAex baselineLedger), x⟩]

def listsOfLen : Nat → List (List Phase)
  | 0 => [[]]
  | n + 1 => (listsOfLen n).flatMap fun l => allPhases.map fun p => p :: l

def insertions (p : Phase) : List Phase → List (List Phase)
  | [] => [[p]]
  | a :: rest => (p :: a :: rest) :: (insertions p rest).map fun l => a :: l

/-- D: every phase column of length <= 5 over the six tags, and the order with one tag inserted. -/
def domainOrder : List Run :=
  ((List.range 6).flatMap listsOfLen ++ allPhases.flatMap fun p => insertions p executionOrder).map
    fun col => ⟨ledgerOf col, false⟩

/-! ### Codes: one self-describing `input=verdict` cell per domain point -/

def bit (b : Bool) : Char := if b then '1' else '0'

def Phase.code : Phase → Char
  | .FP => 'F' | .MTM => 'M' | .SCF => 'S' | .AEX => 'A' | .SEAL => 'L' | .other => 'X'

def PState.code : PState → Char
  | .pass => 'P' | .notApplicable => 'N' | .unknown => 'U' | .fail => 'F' | .invalid => 'I'

def Pred.code : Pred → Char
  | .isTrue => 't' | .isFalse => 'f' | .other => 'o'

def RVal.code : RVal → Char
  | .zero => 'z' | .nonzero => 'n' | .null => 'u'

def Row.code (r : Row) : List Char := [r.state.code, r.pred.code, bit r.hasWhy, bit r.targetNamed]

def Residual.code (r : Residual) : List Char :=
  [bit r.complete, r.outcome.code, r.safety.code, r.evidence.code, r.complexity.code,
    r.portability.code, r.authority.code, r.operability.code]

def Entry.code (e : Entry) : List Char :=
  e.phase.code :: e.row.code ++ (match e.residual with
    | none => []
    | some r => '~' :: r.code)

def Run.code (run : Run) : String :=
  ",".intercalate (run.ledger.map fun e => String.ofList e.code) ++ "|" ++ String.ofList [bit run.crossCycle]

def RowError.code : RowError → String
  | .invalidState => "INVALID" | .failsClosed => "CLOSED" | .naUnjustified => "NA"

def HardKey.code : HardKey → String
  | .safety => "R_safety" | .evidence => "R_evidence" | .authority => "R_authority"

def Err.code : Err → String
  | .order => "ORDER"
  | .row p e => "ROW:" ++ String.ofList [p.code] ++ ":" ++ e.code
  | .residualIncomplete => "RESIDUAL_INCOMPLETE"
  | .notConverged k => "NOT_CONVERGED:" ++ k.code
  | .aexMustActivate => "AEX_MUST_ACTIVATE"
  | .aexMustNameTarget => "AEX_MUST_NAME_TARGET"
  | .aexMustNotActivate => "AEX_MUST_NOT_ACTIVATE"

/-- `<run>=<errors>@<aexRequired>`: the verdict and the one intermediate the validator reports. -/
def Run.cell (run : Run) : String :=
  run.code ++ "=" ++ "+".intercalate ((runErrors run).map Err.code) ++ "@" ++ String.ofList [bit (aexRequired run)]

def runTable (runs : List Run) : String := ";".intercalate (runs.map Run.cell)

/-! ### Decoder, for the sampled joint domain the conformance run supplies as text.
It is not trusted: a cell re-encodes the decoded run, so a wrong decoding shows up as a key the
Python side never asked for. -/

def bitOf : Char → Option Bool
  | '1' => some true | '0' => some false | _ => none

def Phase.ofCode : Char → Option Phase
  | 'F' => some .FP | 'M' => some .MTM | 'S' => some .SCF | 'A' => some .AEX | 'L' => some .SEAL
  | 'X' => some .other | _ => none

def PState.ofCode : Char → Option PState
  | 'P' => some .pass | 'N' => some .notApplicable | 'U' => some .unknown | 'F' => some .fail
  | 'I' => some .invalid | _ => none

def Pred.ofCode : Char → Option Pred
  | 't' => some .isTrue | 'f' => some .isFalse | 'o' => some .other | _ => none

def RVal.ofCode : Char → Option RVal
  | 'z' => some .zero | 'n' => some .nonzero | 'u' => some .null | _ => none

def Residual.decode : List Char → Option Residual
  | [c, o, s, e, x, p, a, q] => do
    pure ⟨← bitOf c, ← RVal.ofCode o, ← RVal.ofCode s, ← RVal.ofCode e, ← RVal.ofCode x,
      ← RVal.ofCode p, ← RVal.ofCode a, ← RVal.ofCode q⟩
  | _ => none

def Entry.decode : List Char → Option Entry
  | p :: s :: d :: w :: t :: rest => do
    let residual ← match rest with
      | [] => some none
      | '~' :: r => (Residual.decode r).map some
      | _ => none
    pure ⟨← Phase.ofCode p, ⟨← PState.ofCode s, ← Pred.ofCode d, ← bitOf w, ← bitOf t⟩, residual⟩
  | _ => none

def splitChars (sep : Char) (cs : List Char) : List (List Char) :=
  let st := cs.foldl (fun (st : List Char × List (List Char)) c =>
    if c = sep then ([], st.1.reverse :: st.2) else (c :: st.1, st.2)) ([], [])
  (st.1.reverse :: st.2).reverse

def Run.decode (cs : List Char) : Option Run :=
  match splitChars '|' cs with
  | [ledger, [x]] => do
    let entries ← if ledger.isEmpty then some [] else (splitChars ',' ledger).mapM Entry.decode
    pure ⟨entries, ← bitOf x⟩
  | _ => none

def decodedTable (keys : String) : String :=
  ";".intercalate ((splitChars ';' keys.toList).map fun cs =>
    match Run.decode cs with
    | some run => run.cell
    | none => "!" ++ String.ofList cs ++ "=DECODE")

/-! ### Tables of sections 2 to 4 -/

def ClaimState.code : ClaimState → Char
  | .supported => 'S' | .unknown => 'U' | .unsupported => 'X'

def Event.code : Event → Char
  | .stop => 'T' | .subagentStop => 'B' | .other => 'O'

def Action.code : Action → Char
  | .allow => 'A' | .block => 'K' | .hardStop => 'H'

def claimTable : String :=
  ";".intercalate (allBools.flatMap fun u => allBools.flatMap fun e => allBools.map fun m =>
    String.ofList [bit u, bit e, bit m, '=', (claimState u e m).code])

def claimLists : List (List ClaimState) :=
  [[]] ++ allClaimStates.map (fun a => [a]) ++
    allClaimStates.flatMap fun a => allClaimStates.map fun b => [a, b]

def gateTable : String :=
  ";".intercalate (allEvents.flatMap fun ev => allBools.flatMap fun i => claimLists.flatMap fun cs =>
    allBools.map fun l =>
      String.ofList ([ev.code, bit i] ++ cs.map ClaimState.code ++ ['/', bit l, '=', bit (gateOk ⟨ev, i, cs, l⟩)]))

def actionTable : String :=
  ";".intercalate (allBools.flatMap fun ok => (List.range 6).flatMap fun prior => allBools.map fun active =>
    String.ofList [bit ok] ++ toString prior ++ String.ofList [bit active, '=', (action ok prior active).code])

def Verdict.code : Verdict → Char
  | .proved => 'P' | .checked => 'C' | .rejected => 'R' | .error => 'E'

def Replay.code : Replay → Char
  | .agrees => 'a' | .disagrees => 'd' | .pending => 'p' | .unavailable => 'u'

def mathTable : String :=
  ";".intercalate (allMathEvidence.map fun e =>
    String.ofList [bit e.receiptIntact, bit e.sourceIntact, bit e.checkerCurrent, e.verdict.code,
      bit e.theoremStated, e.replay.code, '=', bit (mathOk e)])

def subsetsOf : List Nat → List (List Nat)
  | [] => [[]]
  | a :: rest => (subsetsOf rest).flatMap fun s => [s, a :: s]

def authorityTable : String :=
  ";".intercalate ((subsetsOf [0, 1, 2, 3]).flatMap fun before => (subsetsOf [0, 1, 2, 3]).map fun after =>
    String.ofList (before.map fun n => Char.ofNat (48 + n)) ++ ">" ++
      String.ofList (after.map fun n => Char.ofNat (48 + n)) ++ "=" ++
      String.ofList [bit (authoritySubset before after)])

end Fames
