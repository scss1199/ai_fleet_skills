/-!
F1SCore.lean — machine-checked consistency of F1S (FAMES 一套系統) as a rule system.

Operator 2026-10-13: 「依照 ai_ut 的模式用 LEAN 證明 f1s 的合理性 掃過整個架構以後不合理則重新設計 f1s
直到 f1s 完全通過 LEAN 的審查」.  Pattern (ai_ut/ut_theory/rederive): state the rules as a finite model,
prove what holds, let the kernel expose what does not, and feed the refutations back into the rule text.

What is modelled (the F1S text in _registry/fames-protocol.json hot_directive ①–⑥, the T1 rules f1s /
run-until-no-next-step / proof / close-when-done / 禁止問 operator / 授權, and the two Stop hooks):
  * a `Reply` = the observable properties of one assistant turn-ending report;
  * each clause as a decidable predicate on `Reply`;
  * the PROOF / run-until-done hooks as functions Reply → verdict with a block budget;
  * the split of actions between the model (ZCT, must do itself) and the operator (red lines).

Theorems:
  f1s_satisfiable           a single reply satisfies every clause at once (the clauses do not contradict)
  rule1_old_vs_rule6_unsat  the pre-2026-10-13 wording of ① (「細節放檔案」) contradicts ⑥: no reply could
                            satisfy both — this is the refutation that forced the redesign of ①
  honest_reply_not_blocked  a reply satisfying ④⑤⑥ is never blocked by PROOF (no false blocks in the model)
  blocked_implies_violation a PROOF block always names a violated clause (enforcement is sound w.r.t. F1S)
  only_two_hooks_block      every hook other than proof / run-until-done yields allow; a crashed hook allows
  blocks_bounded            a turn is pushed back at most twice, a session at most twelve times (liveness)
  operator_model_disjoint   no action is both reserved to the operator and mandatory for the model
  decision_needs_authority  a 「需要你決定」 is admissible only for an operator-reserved or data-loss decision
  seal_receipts_allowed     the receipts SEAL requires are never "junk" under ⑥
These are statements about the MODEL; `f1s_audit.py` binds them to the texts and to the running hook.
-/
namespace Fames.F1S

/-! ## The reply model -/

structure Reply where
  leadsWithConclusion : Bool      -- ① 結論先行、兩句講完
  listsOriginalWords : Bool       -- ① 原話列需求，不擴不縮不替換
  reasksDecided : Bool            -- ① 已決定的事不再問 (violation when true)
  introducesNewTerms : Bool       -- ① 不引入使用者沒說過的新概念 (violation when true)
  detailsInNewFile : Bool         -- old ① 「細節放檔案」 (a NEW .md / .json written for the details)
  detailsInReplyOrReceipt : Bool  -- new ①: details in the reply or in an existing receipt
  componentsOnDemand : Bool       -- ② 元件按需啟用
  jevWithoutCandidates : Bool     -- ② Jev invoked with < 2 candidates (violation when true)
  reuseBeforeWrite : Bool         -- ③ 先重用再自己寫
  automatedBeforeSimplified : Bool -- ③ 順序不可顛倒 (violation when true)
  codeChangeWithoutSearch : Bool  -- ③ / Brownfield: code touched with no prior usage search (violation when true)
  fixWithoutRegressionTest : Bool -- ④ / tdd: 「修好」 with no green test after the last write (violation when true)
  unprovenClaim : Bool            -- ④ a claim with no tool result / path and no UNKNOWN (violation)
  lies : Bool                     -- ⑤ 已讀/推進/已自動化/做不到 without evidence (violation)
  handsBackModelStep : Bool       -- ⑤ 推託: a model-doable step handed to the operator (violation)
  writesJunkFile : Bool           -- ⑥ unrequested .md / .json outside state / receipts / charter (violation)
  listsNextStepForOperator : Bool -- run-until-no-next-step (violation when true)
  archivesWhenDone : Bool         -- close-when-done
  deriving DecidableEq, Repr

/-! ## The clauses -/

def rule1 (r : Reply) : Bool :=
  r.leadsWithConclusion && r.listsOriginalWords && !r.reasksDecided && !r.introducesNewTerms &&
  r.detailsInReplyOrReceipt
/-- the wording in force before 2026-10-13: details had to go to a file -/
def rule1_old (r : Reply) : Bool :=
  r.leadsWithConclusion && r.listsOriginalWords && !r.reasksDecided && !r.introducesNewTerms &&
  r.detailsInNewFile
def rule2 (r : Reply) : Bool := r.componentsOnDemand && !r.jevWithoutCandidates
def rule3 (r : Reply) : Bool := r.reuseBeforeWrite && !r.automatedBeforeSimplified && !r.codeChangeWithoutSearch
def rule4 (r : Reply) : Bool := !r.unprovenClaim && !r.fixWithoutRegressionTest
def rule5 (r : Reply) : Bool := !r.lies && !r.handsBackModelStep
def rule6 (r : Reply) : Bool := !r.writesJunkFile && !r.detailsInNewFile
def ruleRunUntilDone (r : Reply) : Bool := !r.listsNextStepForOperator
def ruleCloseWhenDone (r : Reply) : Bool := r.archivesWhenDone

def clauses : List (String × (Reply → Bool)) :=
  [("①不准曲解", rule1), ("②不准誤用", rule2), ("③馬斯克五步", rule3), ("④證據否則UNKNOWN", rule4),
   ("⑤不准說謊推託", rule5), ("⑥不准隨意產出檔案", rule6), ("run-until-no-next-step", ruleRunUntilDone),
   ("close-when-done", ruleCloseWhenDone)]

def satisfiesAll (r : Reply) : Bool := clauses.all fun c => c.2 r

/-- A fully compliant reply. -/
def exemplar : Reply :=
  { leadsWithConclusion := true, listsOriginalWords := true, reasksDecided := false, introducesNewTerms := false,
    detailsInNewFile := false, detailsInReplyOrReceipt := true, componentsOnDemand := true,
    jevWithoutCandidates := false, reuseBeforeWrite := true, automatedBeforeSimplified := false,
    codeChangeWithoutSearch := false, fixWithoutRegressionTest := false,
    unprovenClaim := false, lies := false, handsBackModelStep := false, writesJunkFile := false,
    listsNextStepForOperator := false, archivesWhenDone := true }

theorem f1s_satisfiable : satisfiesAll exemplar = true := by decide

/-- The refutation: the old ① and ⑥ cannot both hold for any reply. -/
theorem rule1_old_vs_rule6_unsat : ∀ r : Reply, ¬ (rule1_old r = true ∧ rule6 r = true) := by
  intro r h
  cases hd : r.detailsInNewFile <;> simp [rule1_old, rule6, hd] at h

/-! ## The hooks -/

inductive Hook | proof | runUntilDone | claimIntegrity | sessionContext | skillAudit | agcPrecompact
  deriving DecidableEq, Repr

inductive Verdict | allow | block
  deriving DecidableEq, Repr

/-- PROOF judges ④⑤⑥ and the ③ code-change clause (claims without evidence, lies / hand-backs, junk files,
code touched without a prior search). -/
def proofVerdict (r : Reply) : Verdict :=
  if rule4 r && rule5 r && rule6 r && !r.codeChangeWithoutSearch then .allow else .block

/-- run-until-done judges only the trailing next-step list. -/
def runUntilDoneVerdict (r : Reply) : Verdict :=
  if ruleRunUntilDone r then .allow else .block

/-- Every hook: `crashed = true` means the launcher caught an exception (fail-open). -/
def hookVerdict (h : Hook) (crashed : Bool) (r : Reply) : Verdict :=
  if crashed then .allow else
  match h with
  | .proof => proofVerdict r
  | .runUntilDone => runUntilDoneVerdict r
  | _ => .allow

theorem honest_reply_not_blocked (r : Reply) (h4 : rule4 r = true) (h5 : rule5 r = true) (h6 : rule6 r = true)
    (h3 : r.codeChangeWithoutSearch = false) : proofVerdict r = .allow := by
  simp [proofVerdict, h4, h5, h6, h3]

theorem blocked_implies_violation (r : Reply) (h : proofVerdict r = .block) :
    rule4 r = false ∨ rule5 r = false ∨ rule6 r = false ∨ rule3 r = false := by
  by_cases h4 : rule4 r = true <;> by_cases h5 : rule5 r = true <;> by_cases h6 : rule6 r = true <;>
    by_cases h3 : r.codeChangeWithoutSearch = true <;> simp_all [proofVerdict, rule3]

theorem only_two_hooks_block (h : Hook) (crashed : Bool) (r : Reply)
    (hv : hookVerdict h crashed r = .block) : (h = .proof ∨ h = .runUntilDone) ∧ crashed = false := by
  cases h <;> cases crashed <;> simp_all [hookVerdict]

/-- Block budget: the n-th push-back of a turn is issued only while n < perTurn and the session
total < perSession; afterwards the hook allows (the turn ends). -/
def pushAllowed (perTurn perSession turnBlocks sessionBlocks : Nat) : Bool :=
  turnBlocks < perTurn && sessionBlocks < perSession

theorem blocks_bounded (turnBlocks sessionBlocks : Nat)
    (h : pushAllowed 2 12 turnBlocks sessionBlocks = true) : turnBlocks < 2 ∧ sessionBlocks < 12 := by
  simpa [pushAllowed] using h

/-! ## Who does what -/

inductive Action
  | gitCommitPush | deploy | build | packageUpgrade | riderProposal | credentialCheck | readData | runTests
  | interactiveOauthLogin | permanentDelete | riderArming | globalClaudeSettings | secretValue | fundsTransfer
  | hardware | reboot | dataLossDecision
  deriving DecidableEq, Repr

/-- T1 禁止問 operator: mechanical work the model must do itself (ZCT). -/
def modelMandatory : List Action :=
  [.gitCommitPush, .deploy, .build, .packageUpgrade, .riderProposal, .credentialCheck, .readData, .runTests]

/-- Red lines / 授權 / ⑤: steps reserved to the operator. -/
def operatorReserved : List Action :=
  [.interactiveOauthLogin, .permanentDelete, .riderArming, .globalClaudeSettings, .secretValue,
   .fundsTransfer, .hardware, .reboot, .dataLossDecision]

theorem operator_model_disjoint : ∀ a : Action, ¬ (a ∈ modelMandatory ∧ a ∈ operatorReserved) := by
  intro a; cases a <;> decide

/-- A decision request to the operator is admissible only when it is theirs to make. -/
def decisionAdmissible (askedBefore : Bool) (subject : Action) : Bool :=
  !askedBefore && (subject ∈ operatorReserved)

theorem decision_needs_authority (askedBefore : Bool) (a : Action)
    (h : decisionAdmissible askedBefore a = true) : askedBefore = false ∧ a ∈ operatorReserved := by
  simp [decisionAdmissible] at h
  exact h

theorem model_step_never_a_decision (askedBefore : Bool) (a : Action) (ha : a ∈ modelMandatory) :
    decisionAdmissible askedBefore a = false := by
  have hb := eq_false (fun hb => operator_model_disjoint a ⟨ha, hb⟩)
  simp [decisionAdmissible, hb]

/-! ## Files ⑥ -/

-- submit: a seat's hand-off to the curator under _inbox/from_projects/<seat>/ (charter-required; ai_ut 2026-10-15
-- found it missing, so every SUBMIT modelled as junk under ⑥ while claude-proof-hook already allowed _inbox).
inductive FileKind | stateRegistry | sealReceipt | charter | requestedByPrompt | submit | report | note | summary | memoryProse
  deriving DecidableEq, Repr

def allowedFile : FileKind → Bool
  | .stateRegistry | .sealReceipt | .charter | .requestedByPrompt | .submit => true
  | _ => false

def sealRequires : List FileKind := [.sealReceipt]

theorem seal_receipts_allowed : ∀ k ∈ sealRequires, allowedFile k = true := by decide

theorem reports_are_junk : allowedFile .report = false ∧ allowedFile .note = false ∧
    allowedFile .summary = false ∧ allowedFile .memoryProse = false := by decide

/-- ai_ut 2026-10-15 (`aiut_prev_submit_ok`): a charter-required SUBMIT hand-off is not junk under ⑥. -/
theorem submit_allowed : allowedFile .submit = true := by decide

/-! ## Threads @nashlikeai 2026-10-14 (skills.sh top list) checked against F1S -/

/-- tdd: a reply that passes ④ never claims a fix without a regression test after the last write. -/
theorem tdd_inside_rule4 (r : Reply) (h : rule4 r = true) : r.fixWithoutRegressionTest = false := by
  simp [rule4] at h
  exact h.2

/-- grill-me (「AI 會一直追問你，直到搞懂」) is refuted as written: a second question on the same subject is
never admissible, and a question on anything the model must do itself is never admissible either.
F1S keeps the useful half as self-interrogation (grill-with-docs = search the repo / docs first,
ClaimContract.ask_value_needs_search) and ① 「真有兩種讀法時選最貼近原話的一種直接做」. -/
theorem grill_me_reask_inadmissible (a : Action) : decisionAdmissible true a = false := by
  simp [decisionAdmissible]

theorem grill_me_model_question_inadmissible (a : Action) (ha : a ∈ modelMandatory) :
    decisionAdmissible false a = false :=
  model_step_never_a_decision false a ha

end Fames.F1S
