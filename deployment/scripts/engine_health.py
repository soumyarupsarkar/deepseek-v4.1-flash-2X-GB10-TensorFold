"""Interpret measured native engine counters without inventing Python counters."""


def healthy(value):
    native = value.get('native')
    return (isinstance(native, dict) and value.get('status') == 'ok'
            and value.get('runtime_poisoned') is False
            and native.get('rdma_failed') is False)


def ready(value, profile):
    native = value.get('native', {})
    return (healthy(value) and not value.get('warming', True)
            and native.get('pool_tokens') == profile['pool_tokens']
            and native.get('context_tokens') == profile['context']
            and native.get('stream_slots') == profile['parallel']
            and value.get('max_batch_size') == profile['parallel']
            and value.get('max_model_len') == profile['context']
            and value.get('structured_outputs') is True)


def busy(value):
    scheduler = value.get('scheduler', {})
    native = value.get('native', {})
    return any(scheduler.get(k, 0) > 0 for k in ('running', 'waiting')) or native.get('prefilling_streams', 0) > 0


def progress(value):
    # Prefill progress advances after every completed chunk, even before the
    # first output token of a million-token request. Rates are not counters.
    native = value.get('native', {})
    completed = value.get('completed', {})
    return (tuple(native.get(k) for k in ('prefill_tokens', 'verify_rounds', 'draft_passes')),
            tuple(completed.get(k) for k in ('prompt_tokens', 'generation_tokens', 'decode_rounds')),
            value.get('scheduler', {}).get('generation_tokens_running'))
