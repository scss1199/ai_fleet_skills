/-!
Runtime phase-admission extension of FamesKernel.lean.
The conformance composer inserts this fragment inside namespace Fames, after the
existing authority proofs. Phase and authoritySubset are the existing model.
Evidence facts are produced by a hash-bound, replayed runtime verifier. These
theorems do not establish facts about the outside world without that verifier.
-/
namespace PhaseContract

structure Facts where
  goalBound : Bool
  authorityBound : Bool
  acceptanceBound : Bool
  skillsBound : Bool
  resultVerified : Bool
  identityFresh : Bool
  evidenceFresh : Bool
  residualMeasured : Bool
  residualComparable : Bool
  crossCycle : Bool
  boundariesPreserved : Bool
  graphClosed : Bool
  deriving DecidableEq, Repr

def active (phase : Phase) (f : Facts) : Bool :=
  match phase with
  | .SCF => f.resultVerified && f.identityFresh
  | .AEX => f.crossCycle && f.residualMeasured && f.residualComparable
  | .other => false
  | _ => true

def phaseCore (phase : Phase) (f : Facts) : Bool :=
  match phase with
  | .FP => f.goalBound && f.authorityBound && f.acceptanceBound
  | .MTM => f.skillsBound && f.authorityBound
  | .SCF => f.resultVerified && f.identityFresh
  | .AEX => f.resultVerified && f.identityFresh && f.crossCycle &&
      f.residualMeasured && f.residualComparable
  | .SEAL => f.goalBound && f.authorityBound && f.acceptanceBound &&
      f.resultVerified && f.identityFresh && f.evidenceFresh &&
      f.boundariesPreserved && f.graphClosed
  | .other => false

def phaseAllowed (phase : Phase) (skip hasWhy : Bool) (f : Facts) : Bool :=
  if skip then ((phase == .SCF || phase == .AEX) && (!active phase f && hasWhy))
  else active phase f && phaseCore phase f

def transition (expected phase : Phase) (bound priorValid : Bool)
    (before after : List Nat) (ready : Bool) : Bool :=
  bound && (priorValid && ((expected == phase) && (authoritySubset before after && ready)))

def nextPhase : Phase → Phase
  | .FP => .MTM | .MTM => .SCF | .SCF => .AEX | .AEX => .SEAL
  | .SEAL => .other | .other => .other

def advance (expected phase : Phase) (bound priorValid : Bool)
    (before after : List Nat) (skip hasWhy : Bool) (f : Facts) : Option Phase :=
  if transition expected phase bound priorValid before after (phaseAllowed phase skip hasWhy f)
  then some (nextPhase phase) else none

theorem transition_iff (expected phase : Phase) (bound priorValid ready : Bool)
    (before after : List Nat) :
    transition expected phase bound priorValid before after ready = true ↔
      bound = true ∧ priorValid = true ∧ expected = phase ∧
      authoritySubset before after = true ∧ ready = true := by
  simp [transition]

theorem accepted_transition_preserves_authority (expected phase : Phase)
    (bound priorValid ready : Bool) (before after : List Nat)
    (h : transition expected phase bound priorValid before after ready = true) :
    ∀ scope, scope ∈ after → scope ∈ before := by
  exact authority_subset_sound before after ((transition_iff _ _ _ _ _ _ _).1 h).2.2.2.1

theorem accepted_transition_cannot_skip_phase (expected phase : Phase)
    (bound priorValid ready : Bool) (before after : List Nat)
    (h : transition expected phase bound priorValid before after ready = true) :
    expected = phase ∧ bound = true ∧ priorValid = true := by
  have ht := (transition_iff _ _ _ _ _ _ _).1 h
  exact ⟨ht.2.2.1, ht.1, ht.2.1⟩

def traceOk (initial : List Nat) : List (List Nat) → Bool
  | [] => true
  | next :: rest => authoritySubset initial next && traceOk next rest

def finalAuthority (initial : List Nat) : List (List Nat) → List Nat
  | [] => initial
  | next :: rest => finalAuthority next rest

theorem arbitrarily_long_authority_trace_narrows (initial : List Nat) (trace : List (List Nat))
    (h : traceOk initial trace = true) :
    authoritySubset initial (finalAuthority initial trace) = true := by
  induction trace generalizing initial with
  | nil =>
    apply List.all_eq_true.2
    intro x hx
    simpa [finalAuthority] using hx
  | cons next rest ih =>
    have hs : authoritySubset initial next = true ∧ traceOk next rest = true := by
      simpa [traceOk] using h
    exact authority_subset_trans initial next _ hs.1 (ih next hs.2)

theorem fp_admission_binds_goal_authority_acceptance (f : Facts) (why : Bool)
    (h : phaseAllowed .FP false why f = true) :
    f.goalBound = true ∧ f.authorityBound = true ∧ f.acceptanceBound = true := by
  simpa [phaseAllowed, active, phaseCore, Bool.and_assoc] using h

theorem mtm_admission_binds_skills (f : Facts) (why : Bool)
    (h : phaseAllowed .MTM false why f = true) :
    f.skillsBound = true ∧ f.authorityBound = true := by
  simpa [phaseAllowed, active, phaseCore] using h

theorem scf_execution_needs_verified_current_result (f : Facts) (why : Bool)
    (h : phaseAllowed .SCF false why f = true) :
    f.resultVerified = true ∧ f.identityFresh = true := by
  simpa [phaseAllowed, active, phaseCore] using h

theorem aex_execution_needs_measured_comparable_residual (f : Facts) (why : Bool)
    (h : phaseAllowed .AEX false why f = true) :
    f.resultVerified = true ∧ f.identityFresh = true ∧ f.crossCycle = true ∧
      f.residualMeasured = true ∧ f.residualComparable = true := by
  simpa [phaseAllowed, active, phaseCore, Bool.and_assoc, and_assoc, and_left_comm, and_comm] using h

theorem skips_are_only_explicit_inactive_scf_or_aex (phase : Phase) (f : Facts) (why : Bool)
    (h : phaseAllowed phase true why f = true) :
    (phase = .SCF ∨ phase = .AEX) ∧ active phase f = false ∧ why = true := by
  simpa [phaseAllowed] using h

theorem seal_requires_verified_fresh_closed_result (f : Facts) (why : Bool)
    (h : phaseAllowed .SEAL false why f = true) :
    f.goalBound = true ∧ f.authorityBound = true ∧ f.acceptanceBound = true ∧
    f.resultVerified = true ∧ f.identityFresh = true ∧ f.evidenceFresh = true ∧
    f.boundariesPreserved = true ∧ f.graphClosed = true := by
  simpa [phaseAllowed, active, phaseCore, Bool.and_assoc] using h

theorem rejected_admission_cannot_advance (expected phase : Phase) (bound priorValid : Bool)
    (before after : List Nat) (skip why : Bool) (f : Facts)
    (h : phaseAllowed phase skip why f = false) :
    advance expected phase bound priorValid before after skip why f = none := by
  simp [advance, transition, h]

def factsOf (n : Nat) : Facts :=
  ⟨n.testBit 0, n.testBit 1, n.testBit 2, n.testBit 3, n.testBit 4, n.testBit 5,
   n.testBit 6, n.testBit 7, n.testBit 8, n.testBit 9, n.testBit 10, n.testBit 11⟩

def phases : List Phase := [.FP, .MTM, .SCF, .AEX, .SEAL, .other]
def bools : List Bool := [false, true]
def authorities : List (List Nat) := [[], [0], [1], [0, 1]]
def charOf (b : Bool) : Char := if b then '1' else '0'

def phaseTable : String := String.ofList <|
  phases.flatMap fun phase => bools.flatMap fun skip => bools.flatMap fun why =>
    (List.range 4096).map fun mask => charOf (phaseAllowed phase skip why (factsOf mask))

def transitionTable : String := String.ofList <|
  phases.flatMap fun expected => phases.flatMap fun phase => bools.flatMap fun bound =>
    bools.flatMap fun prior => bools.flatMap fun ready => authorities.flatMap fun before =>
      authorities.map fun after => charOf (transition expected phase bound prior before after ready)

end PhaseContract
