"""Displace retained prefixes before testing a deliberately fragmented layout.

Only synthetic loopback requests are used. Equal, chunk-aligned reservations
cover the complete logical pool. Short prompts cannot save a native snapshot;
after cancelling these owned sockets there are no valid kept extents to alter
the following first-fit fixture. No configuration or service lifecycle changes.
"""
import hashlib
from pathlib import Path
import time

CHUNK_ROWS = 2048


def reservation_plan(profile):
    pool, streams, context = (profile[k] for k in ('pool_tokens', 'parallel', 'context'))
    rows = int(profile['environment']['TF_DS_ROUND_ROWS'])
    if any(type(v) is not int or v <= 0 for v in (pool, streams, context, rows)):
        raise ValueError('Require positive integer capacities')
    if streams > 32 or pool % (streams * CHUNK_ROWS):
        raise ValueError('Equal aligned reservations must cover the pool exactly')
    reservation = pool // streams
    budget = reservation - rows - 2
    if not CHUNK_ROWS <= budget <= context:
        raise ValueError('Reservation token budget is outside the request limits')
    return dict(streams=streams, pool_tokens=pool, reservation_tokens=reservation,
                request_budget=budget, round_rows=rows, chunk_rows=CHUNK_ROWS)


def condition(common, receipt):
    from benchmark import tokens, wait_idle
    from configuration import SOURCE, STATE, profile, read, source_revision
    from engine_health import ready
    from native_decode_compaction import Reader
    from native_endurance import rank_epochs, validate_continuity
    from runtime import atomic, now

    receipt = Path(receipt)
    if receipt.exists() or common.PAIR.config['api']['bind'] != '127.0.0.1':
        raise ValueError('Require a new receipt and an isolated loopback candidate')
    p = profile()
    shape = reservation_plan(p)
    launch = read(STATE / 'launch.json')
    build = read(STATE / 'build.json')
    revision = source_revision()
    if build['revision'] != revision or build['id'] != launch['image'] or launch['profile'] != p:
        raise ValueError('Source, image and profile must match the active launch')
    epochs = rank_epochs(common.PAIR, launch)
    lanes = SOURCE / 'zig/src/families/dsv41/lanes.zig'
    model = SOURCE / 'zig/src/families/dsv41/model.zig'
    source = lanes.read_text()
    required = ('len + s.max_new + m.eng.round_rows + 2',
        'if (at == 0 or at % model.chunk_rows != 0 or at > s.prompt_len -| self.m.cfg.window)',
        'taken[nt] = .{ l.base, l.end }', 'self.staleOver(',
        'for (self.snaps.items) |sn| if (!sn.stale)')
    if not all(part in source for part in required) or 'pub const chunk_rows = 2048;' not in model.read_text():
        raise ValueError('Review the reservation/snapshot proof for the changed engine')
    before, _ = wait_idle(common.API_BASE)
    if not ready(before, p):
        raise ValueError('Candidate is not healthy')
    record = dict(started=now(), status='running', source=revision, image=launch['image'],
        rank_epochs=epochs, shape=shape, health_before=before, fixtures=[],
        engine_files={str(f.relative_to(SOURCE)): hashlib.sha256(f.read_bytes()).hexdigest()
                      for f in (lanes, model)},
        client_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        proof='All disjoint live reservations cover the pool; short prompts cannot save a snapshot. Cancelling only these streams leaves no valid retained extent.')
    atomic(receipt, record)
    readers = []
    try:
        bodies = []
        for index in range(shape['streams']):
            ids = tokens(common.API_BASE, messages=[dict(role='user', content=
                f'Synthetic reservation preparation {index}. Count upward, describing each number in a sentence.')])
            if not 0 < len(ids) < CHUNK_ROWS:
                raise ValueError('A preparation prompt could create a retained snapshot')
            maximum = shape['request_budget'] - len(ids)
            aligned = ((len(ids) + maximum + shape['round_rows'] + 2 + CHUNK_ROWS - 1)
                       // CHUNK_ROWS) * CHUNK_ROWS
            if maximum <= 0 or aligned != shape['reservation_tokens']:
                raise ValueError('Request does not reserve its exact share of the pool')
            bodies.append(dict(model='deepseek-v4.1-flash', prompt=ids,
                max_tokens=maximum, ignore_eos=True, temperature=0, draft=False,
                chat_template_kwargs={'enable_thinking': False}))
            record['fixtures'].append(dict(index=index, prompt_tokens=len(ids),
                maximum_reply_tokens=maximum, reserved_tokens=aligned))
        if sum(f['reserved_tokens'] for f in record['fixtures']) != p['pool_tokens']:
            raise ValueError('Preparation reservations do not cover the entire pool')
        # Launch all sockets without waiting serially for generated text.
        for body in bodies:
            reader = Reader(common.API_BASE, body)
            readers.append(reader)
            reader.start()
        deadline = time.monotonic() + 120
        while True:
            for reader in readers:
                reader.check()
                if reader.done.is_set():
                    raise RuntimeError('A preparation holder ended before full occupancy')
            value = common.PAIR.get('/health')
            if not ready(value, p):
                raise RuntimeError('Candidate became unhealthy during preparation')
            if (all(r.holding.is_set() for r in readers)
                    and value['native']['active_streams'] == shape['streams']
                    and value['native']['prefilling_streams'] == 0
                    and value['scheduler']['running'] == shape['streams']
                    and value['scheduler']['waiting'] == 0):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('Full preparation occupancy was not observed')
            time.sleep(.1)
        record['full'] = value
        atomic(receipt, record)
    except BaseException as exc:
        record.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        for reader in readers:
            reader.cancel()
        cleanup = []
        for reader in readers:
            if reader.thread.ident is not None:
                reader.thread.join(timeout=10)
            if reader.thread.is_alive():
                cleanup.append('Owned preparation reader did not stop')
        try:
            after, drain = wait_idle(common.API_BASE, timeout=30)
            record.update(health_after=after, drain=drain)
            validate_continuity(common.PAIR, launch, epochs,
                read(STATE / 'launch.json'), read(STATE / 'active.json'))
            if record['status'] != 'failed':
                if after['completed']['requests'] - before['completed']['requests'] != shape['streams']:
                    raise ValueError('Unexpected preparation request count')
                record['status'] = 'passed'
        except Exception as exc:
            cleanup.append(type(exc).__name__ + ': ' + str(exc))
        if cleanup:
            record.update(status='failed', cleanup_errors=cleanup)
        record['finished'] = now()
        atomic(receipt, record)
        if cleanup:
            raise RuntimeError('Preparation cleanup or continuity check failed: ' + '; '.join(cleanup))
    return record
