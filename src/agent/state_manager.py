"""
AgentStateManager — sole owner of AgentState transitions.

Architecture reference:
  architecture.md §3.7:
    'The Agent State is the working memory of the loop.  It is an explicit,
    inspectable object that the planner and executor read from and write to.'

  architecture.md §4.6 / requirements.md SR-16:
    AgentState must expose: patient_id, iteration, current_goal,
    completed_goals, pending_goals, conflicts, review_flags,
    low_confidence_pages, evidence_count, completion_score, summary_ready,
    max_iterations_reached.

  requirements.md FR-25:
    Agent State shall be explicit and inspectable.

  requirements.md FR-33c / FR-33d:
    Every iteration increments by exactly one.  The Executor is solely
    responsible for incrementing iteration; no other component shall mutate
    that field.

  implementation_plan.md Phase 9:
    'State transitions must be explicit and inspectable; every transition
    must be writable to the trace by the executor (Phase 11) and trace
    system (Phase 12).'

Design constraints enforced by this module:
  - Every mutating method returns a NEW AgentState via model_copy(update=...).
  - No AgentState is mutated in place.
  - patient_id is preserved unchanged across every transition.
  - iteration is incremented only inside increment_iteration().
  - Storage access is limited to initialize_state() and refresh_*() methods.
  - completion_score is stored by set_completion_score(); it is never derived
    here.  The Planner (Phase 10) owns the scoring formula and readiness
    policy.
  - summary_ready is never derived here.  The Planner (Phase 10) determines
    readiness and applies it via a future set_summary_ready() transition.
  - Loop termination is never decided here.  The Executor / Agent Loop
    (Phase 11) reads AgentState and decides whether to continue.
  - Planner, Tools, and Trace System must not call mutating methods directly —
    only the Executor is permitted to do so.
"""

from src.schemas.agent_state import AgentState, PageReference
from src.storage.storage_service import StorageService


class AgentStateManager:
    """
    Sole owner of all AgentState creation and transitions.

    AgentStateManager is the only component in the system permitted to
    construct or transform AgentState instances.  Every method that
    accepts an AgentState returns a new, valid AgentState — the input is
    never modified.

    Ownership rules:
      - The Executor calls mutating methods and replaces its AgentState
        reference with the returned instance.
      - The Planner receives AgentState read-only and never calls any
        method on AgentStateManager.
      - Tools neither receive nor modify AgentState.

    Phase boundaries respected by this module:
      - completion_score is stored, never derived.  The Planner (Phase 10)
        owns the formula and calls set_completion_score() via the Executor.
      - summary_ready is stored, never derived.  Readiness assessment belongs
        to the Planner (Phase 10); FR-26 assigns that responsibility there.
      - Loop termination predicates belong to the Executor / Agent Loop
        (Phase 11), not here.

    Storage access:
      - initialize_state() and all refresh_*() methods read from
        StorageService to reconcile AgentState with persisted artifacts.
      - All other methods are pure functions of their AgentState argument.

    Configurable threshold (set at construction time):
      low_confidence_threshold:
        Pages whose Page.ocr_confidence is strictly below this value are
        included in AgentState.low_confidence_pages.  Architecture §4.2
        identifies ocr_confidence as the signal that drives
        AgentState.low_confidence_pages.
    """

    def __init__(
        self,
        storage: StorageService,
        *,
        low_confidence_threshold: float = 0.8,
    ) -> None:
        """
        Initialise AgentStateManager with a storage reference and threshold.

        Parameters
        ----------
        storage:
            StorageService instance used by initialize_state() and refresh_*()
            to read persisted artifacts.  All reads go through this surface
            in line with the storage-layer contract (NFR-8).
        low_confidence_threshold:
            Pages with Page.ocr_confidence strictly below this value are
            included in AgentState.low_confidence_pages.  Must be in the
            range (0.0, 1.0].  Defaults to 0.8.

        Raises
        ------
        ValueError
            If low_confidence_threshold is outside the allowed range.
        """
        if not (0.0 < low_confidence_threshold <= 1.0):
            raise ValueError(
                "low_confidence_threshold must be in (0.0, 1.0]; "
                f"got {low_confidence_threshold!r}"
            )
        self._storage = storage
        self._low_confidence_threshold = low_confidence_threshold

    # =========================================================================
    # Initialization
    # =========================================================================

    def initialize_state(self, patient_id: str) -> AgentState:
        """
        Create the initial AgentState for a patient's agent loop run.

        Loads all currently stored artifacts for patient_id from
        StorageService and assembles them into a valid starting AgentState
        at iteration 0.

        Storage reads performed:
          - get_evidence_for_patient()      → evidence_count
          - get_conflicts_for_patient()     → conflicts
          - get_review_flags_for_patient()  → review_flags (IDs only)
          - get_pages_for_patient()         → low_confidence_pages

        The returned state has:
          iteration           = 0
          current_goal        = ""  (Planner assigns the first goal via
                                    set_current_goal before the first
                                    iteration)
          completion_score    = 0.0 (schema initial value; the Planner
                                    updates this via set_completion_score)
          summary_ready       = False (schema initial value; the Planner
                                    sets this via a readiness transition)
          max_iterations_reached = False

        Parameters
        ----------
        patient_id:
            Stable identifier of the Patient record this run processes.
            Architecture §3.1, SR-4.

        Returns
        -------
        AgentState
            A fully populated, valid initial state.
        """
        evidence_count = len(
            self._storage.get_evidence_for_patient(patient_id)
        )

        conflicts = self._storage.get_conflicts_for_patient(patient_id)

        review_flag_ids = [
            flag.flag_id
            for flag in self._storage.get_review_flags_for_patient(patient_id)
        ]

        low_confidence_pages = [
            PageReference(
                document_name=page.document_name,
                page_number=page.page_number,
            )
            for page in self._storage.get_pages_for_patient(patient_id)
            if page.ocr_confidence < self._low_confidence_threshold
        ]

        return AgentState(
            patient_id=patient_id,
            iteration=0,
            current_goal="",
            completed_goals=[],
            pending_goals=[],
            conflicts=conflicts,
            review_flags=review_flag_ids,
            low_confidence_pages=low_confidence_pages,
            evidence_count=evidence_count,
            completion_score=0.0,
            summary_ready=False,
            max_iterations_reached=False,
        )

    # =========================================================================
    # Goal transitions
    # =========================================================================

    def set_current_goal(self, state: AgentState, goal: str) -> AgentState:
        """
        Set the active goal the Planner is working toward.

        Called by the Executor when applying a Planner decision that
        introduces or changes the current goal.  The goal string is recorded
        in every TraceStep emitted during the iteration.

        Parameters
        ----------
        state:
            Current AgentState.  Not modified.
        goal:
            The new current goal.  The Planner supplies this value via its
            decision output.

        Returns
        -------
        AgentState
            New state with current_goal replaced by goal.  All other fields
            are unchanged.
        """
        return state.model_copy(update={"current_goal": goal})

    def set_pending_goals(
        self, state: AgentState, goals: list[str]
    ) -> AgentState:
        """
        Replace the full pending_goals list.

        Called by the Executor when the Planner identifies a new set of
        goals that have not yet been actioned.  Passing an empty list clears
        all pending work.

        Parameters
        ----------
        state:
            Current AgentState.  Not modified.
        goals:
            New pending_goals list.  A copy is stored to decouple the
            returned state from the caller's reference.

        Returns
        -------
        AgentState
            New state with pending_goals replaced.  All other fields are
            unchanged.
        """
        return state.model_copy(update={"pending_goals": list(goals)})

    def mark_current_goal_completed(self, state: AgentState) -> AgentState:
        """
        Move the current goal into completed_goals and clear current_goal.

        Called by the Executor once a tool action that satisfies the active
        goal has been successfully executed and persisted.  After this
        transition, current_goal is the empty string until the Planner
        selects the next goal via set_current_goal().

        If current_goal is already empty this method is a no-op — an
        empty string is not appended to completed_goals because it does not
        represent an achieved goal.

        Parameters
        ----------
        state:
            Current AgentState.  Not modified.

        Returns
        -------
        AgentState
            New state with the previous current_goal appended to
            completed_goals and current_goal set to "".
        """
        if not state.current_goal:
            return state.model_copy(update={})

        updated_completed = [*state.completed_goals, state.current_goal]
        return state.model_copy(
            update={
                "completed_goals": updated_completed,
                "current_goal": "",
            }
        )

    # =========================================================================
    # Artifact refresh transitions
    # =========================================================================

    def refresh_conflicts(self, state: AgentState) -> AgentState:
        """
        Reload conflicts from storage and replace AgentState.conflicts.

        Called by the Executor after the Conflict Detection Tool has
        persisted new Conflict records.  Keeps AgentState.conflicts in sync
        with the authoritative Conflict Store.

        AgentState.conflicts holds embedded Conflict objects (not IDs) so
        that the Planner can reason over conflict content without a storage
        round-trip.

        Storage read performed:
          get_conflicts_for_patient(state.patient_id)

        Parameters
        ----------
        state:
            Current AgentState.  Not modified.

        Returns
        -------
        AgentState
            New state with conflicts replaced from storage.
        """
        conflicts = self._storage.get_conflicts_for_patient(state.patient_id)
        return state.model_copy(update={"conflicts": conflicts})

    def refresh_review_flags(self, state: AgentState) -> AgentState:
        """
        Reload review flag IDs from storage and replace AgentState.review_flags.

        Called by the Executor after any tool persists a new ReviewFlag
        record.  AgentState.review_flags stores only flag_id strings to
        keep state lean; full ReviewFlag objects remain in the Review Flag
        Store and are resolved by downstream consumers via StorageService.

        Storage read performed:
          get_review_flags_for_patient(state.patient_id)

        Parameters
        ----------
        state:
            Current AgentState.  Not modified.

        Returns
        -------
        AgentState
            New state with review_flags replaced by the current list of
            flag_id strings from storage.
        """
        flag_ids = [
            flag.flag_id
            for flag in self._storage.get_review_flags_for_patient(
                state.patient_id
            )
        ]
        return state.model_copy(update={"review_flags": flag_ids})

    def refresh_low_confidence_pages(self, state: AgentState) -> AgentState:
        """
        Reload low-confidence page references from storage.

        Called by the Executor after OCR or OCR Retry output has been
        persisted to the Page Store.  Re-evaluates which pages fall below
        the configured low_confidence_threshold so that the OCR Retry Tool
        can read AgentState.low_confidence_pages directly (SR-18).

        Storage read performed:
          get_pages_for_patient(state.patient_id)

        Parameters
        ----------
        state:
            Current AgentState.  Not modified.

        Returns
        -------
        AgentState
            New state with low_confidence_pages replaced by PageReference
            objects for all pages whose ocr_confidence is strictly below
            self._low_confidence_threshold.
        """
        low_confidence_pages = [
            PageReference(
                document_name=page.document_name,
                page_number=page.page_number,
            )
            for page in self._storage.get_pages_for_patient(state.patient_id)
            if page.ocr_confidence < self._low_confidence_threshold
        ]
        return state.model_copy(
            update={"low_confidence_pages": low_confidence_pages}
        )

    def refresh_evidence_count(self, state: AgentState) -> AgentState:
        """
        Reload the evidence count from storage.

        Called by the Executor after the Evidence Validation Tool has
        admitted new Evidence records.  Keeps evidence_count in sync with
        the Evidence Store.

        Storage read performed:
          get_evidence_for_patient(state.patient_id)

        Parameters
        ----------
        state:
            Current AgentState.  Not modified.

        Returns
        -------
        AgentState
            New state with evidence_count updated to the current count of
            validated Evidence records in storage.
        """
        count = len(
            self._storage.get_evidence_for_patient(state.patient_id)
        )
        return state.model_copy(update={"evidence_count": count})

    # =========================================================================
    # Score and readiness storage transitions
    # =========================================================================

    def set_completion_score(
        self, state: AgentState, score: float
    ) -> AgentState:
        """
        Store a completion_score computed externally by the Planner.

        AgentStateManager does not derive completion_score.  The Planner
        (Phase 10) owns the scoring formula and readiness policy
        (requirements.md FR-26, implementation_plan.md Phase 10).  The
        Executor calls this method to apply the Planner's computed score to
        AgentState.

        Parameters
        ----------
        state:
            Current AgentState.  Not modified.
        score:
            Completion score in [0.0, 1.0] computed by the Planner.
            The AgentState schema enforces the range invariant; this method
            validates the value before constructing the new state so that
            callers receive a clear error on an out-of-range input.

        Returns
        -------
        AgentState
            New state with completion_score set to score.  All other fields
            are unchanged.

        Raises
        ------
        ValueError
            If score is outside [0.0, 1.0].
        """
        if not (0.0 <= score <= 1.0):
            raise ValueError(
                f"completion_score must be in [0.0, 1.0]; got {score!r}"
            )
        return state.model_copy(update={"completion_score": score})

    # =========================================================================
    # Iteration transition
    # =========================================================================

    def increment_iteration(
        self, state: AgentState, max_iterations: int
    ) -> AgentState:
        """
        Increment iteration by exactly one and derive max_iterations_reached.

        This is the only method that may change AgentState.iteration.  The
        Executor must call it exactly once per agent-loop iteration, after
        the tool action for that iteration has been executed and persisted
        (FR-33c, FR-33d).

        max_iterations_reached is derived from the post-increment iteration
        value against max_iterations (FR-33a).  The derivation uses the
        post-increment value so the loop may complete the last permitted
        iteration before the flag is raised.

        Parameters
        ----------
        state:
            Current AgentState.  Not modified.
        max_iterations:
            The configurable MAX_AGENT_ITERATIONS limit (FR-33a).  Must be
            >= 1.

        Returns
        -------
        AgentState
            New state with iteration incremented by one and
            max_iterations_reached set accordingly.

        Raises
        ------
        ValueError
            If max_iterations is less than 1.
        """
        if max_iterations < 1:
            raise ValueError(
                f"max_iterations must be >= 1; got {max_iterations!r}"
            )
        new_iteration = state.iteration + 1
        return state.model_copy(
            update={
                "iteration": new_iteration,
                "max_iterations_reached": new_iteration >= max_iterations,
            }
        )
