// Synchronous identity checks and cancellation barriers share the plugin event loop.
export class Runs {
  constructor(instance) { this.instance = instance; this.current = new Map(); this.stopping = new Set(); this.cancelled = new Set(); }
  begin(session, run) {
    if (this.stopping.has(session)) throw new Error('Previous run is stopping; retry this turn after it stops.');
    if (this.cancelled.has(run)) throw new Error('This run was cancelled. Submit a new user turn.');
    this.current.set(session, run);
    return run;
  }
  async cancel({session_id, run_id, instance_id}, interrupt) {
    if (instance_id !== this.instance || this.current.get(session_id) !== run_id)
      return {status:'stale_run', interrupted:false};
    if (this.stopping.has(session_id)) return {status:'stopping', interrupted:false};
    // No await between comparison and barrier. A prompt arriving during the
    // interrupt is refused instead of becoming an accidentally cancelled run.
    this.stopping.add(session_id); this.cancelled.add(run_id);
    try {
      const result = await interrupt(session_id);
      return {status:result.interrupted ? 'interrupted' : 'idle', interrupted:result.interrupted};
    } finally { this.stopping.delete(session_id); }
  }
}
