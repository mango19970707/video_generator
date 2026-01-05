def split_text(text: str) -> list[str]:
    """Splits text into sentences."""
    tmp_sentences = text.split('\n')
    final_sentences = []
    for sentence in tmp_sentences:
        # Split by Chinese period
        tmp = sentence.split('。')
        for t in tmp:
            if t.strip() != '':
                final_sentences.append(t.strip())
    return final_sentences