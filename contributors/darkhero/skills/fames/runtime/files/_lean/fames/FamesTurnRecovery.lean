/-!
Turn-recovery admission only. These facts must be recomputed from original native
evidence by the caller. This model neither authenticates artifacts nor proves
task completion, free-form claims, deployment, or host-wide runtime coverage.
-/
namespace Fames.TurnRecovery

structure Facts where
  sameSession : Bool
  exactPrompt : Bool
  sameSeat : Bool
  nativeOriginVerified : Bool
  originalReceiptFresh : Bool
  sourceHashBound : Bool
  deriving DecidableEq, Repr

def authoritySubset (before after : List String) : Bool :=
  after.all fun scope => before.contains scope

def recoveryAllowed (f : Facts) (before after : List String) : Bool :=
  f.sameSession && f.exactPrompt && f.sameSeat && f.nativeOriginVerified &&
    f.originalReceiptFresh && f.sourceHashBound && authoritySubset before after

/-- Advice has no effect on admission; admission never grants completion. -/
def decision (f : Facts) (before after : List String) (_jevAdvice : Bool) : Bool × Bool :=
  (recoveryAllowed f before after, false)

theorem recovery_iff (f : Facts) (before after : List String) :
    recoveryAllowed f before after = true ↔
      f.sameSession = true ∧ f.exactPrompt = true ∧ f.sameSeat = true ∧
      f.nativeOriginVerified = true ∧ f.originalReceiptFresh = true ∧
      f.sourceHashBound = true ∧ authoritySubset before after = true := by
  simp [recoveryAllowed, Bool.and_assoc]

theorem accepted_recovery_requires_original_identity (f : Facts) (before after : List String)
    (h : recoveryAllowed f before after = true) :
    f.sameSession = true ∧ f.exactPrompt = true ∧ f.sameSeat = true ∧
      f.nativeOriginVerified = true ∧ f.originalReceiptFresh = true ∧
      f.sourceHashBound = true := by
  have hf := (recovery_iff f before after).1 h
  exact ⟨hf.1, hf.2.1, hf.2.2.1, hf.2.2.2.1, hf.2.2.2.2.1, hf.2.2.2.2.2.1⟩

theorem accepted_recovery_preserves_authority (f : Facts) (before after : List String)
    (h : recoveryAllowed f before after = true) :
    ∀ scope, scope ∈ after → scope ∈ before := by
  have hs := (recovery_iff f before after).1 h |>.2.2.2.2.2.2
  intro scope member
  have hb := List.all_eq_true.1 hs scope member
  simpa using hb

theorem recovery_never_authorizes_completion (f : Facts) (before after : List String)
    (advice : Bool) : (decision f before after advice).2 = false := by
  rfl

theorem jev_advice_cannot_change_admission (f : Facts) (before after : List String)
    (a b : Bool) : decision f before after a = decision f before after b := by
  rfl

theorem absent_native_evidence_rejects_even_with_advice (f : Facts)
    (before after : List String) (h : f.nativeOriginVerified = false) :
    (decision f before after true).1 = false := by
  simp [decision, recoveryAllowed, h]

def factsOf (n : Nat) : Facts :=
  ⟨n.testBit 0, n.testBit 1, n.testBit 2, n.testBit 3, n.testBit 4, n.testBit 5⟩

def authorities : List (List String) := [[], ["read"], ["repair"], ["read", "repair"]]
def bools : List Bool := [false, true]
def charOf (b : Bool) : Char := if b then '1' else '0'

def admissionTable : String := String.ofList <|
  (List.range 64).flatMap fun mask => authorities.flatMap fun before =>
    authorities.flatMap fun after => bools.map fun advice =>
      charOf (decision (factsOf mask) before after advice).1

def completionTable : String := String.ofList <|
  (List.range 64).flatMap fun mask => authorities.flatMap fun before =>
    authorities.flatMap fun after => bools.map fun advice =>
      charOf (decision (factsOf mask) before after advice).2

end Fames.TurnRecovery
