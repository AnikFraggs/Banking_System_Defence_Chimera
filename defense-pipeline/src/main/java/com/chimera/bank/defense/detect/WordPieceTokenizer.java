package com.chimera.bank.defense.detect;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Bounded BERT-style basic tokenization followed by greedy WordPiece. */
public final class WordPieceTokenizer {
    private static final int MAX_WORD_CODE_POINTS = 100;
    private static final int MAX_VOCAB_ENTRIES = 200_000;

    public record Tokenized(long[] inputIds, long[] attentionMask, long[] tokenTypeIds) {}

    private final Map<String, Integer> vocab = new HashMap<>();
    private final int maxSequenceLength;
    private final int maxInputCodePoints;
    private final int clsId;
    private final int sepId;
    private final int unkId;
    private final int padId;

    public WordPieceTokenizer(Path vocabFile, int maxSequenceLength, int maxInputCodePoints) throws IOException {
        if (maxSequenceLength < 8 || maxSequenceLength > 512) {
            throw new IllegalArgumentException("Semantic max sequence length must be between 8 and 512");
        }
        if (maxInputCodePoints < 1 || maxInputCodePoints > 65_536) {
            throw new IllegalArgumentException("Semantic input bound must be between 1 and 65536 code points");
        }
        this.maxSequenceLength = maxSequenceLength;
        this.maxInputCodePoints = maxInputCodePoints;
        try (BufferedReader reader = Files.newBufferedReader(vocabFile, StandardCharsets.UTF_8)) {
            String token;
            int id = 0;
            while ((token = reader.readLine()) != null) {
                if (id >= MAX_VOCAB_ENTRIES) throw new IOException("WordPiece vocabulary is too large");
                vocab.putIfAbsent(token, id++);
            }
        }
        clsId = required("[CLS]");
        sepId = required("[SEP]");
        unkId = required("[UNK]");
        padId = vocab.getOrDefault("[PAD]", 0);
    }

    public Tokenized tokenize(String value) {
        String text = value == null ? "" : value;
        int codePoints = text.codePointCount(0, text.length());
        if (codePoints > maxInputCodePoints) {
            text = text.substring(0, text.offsetByCodePoints(0, maxInputCodePoints));
        }
        text = Normalizer.normalize(text, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);

        List<Integer> ids = new ArrayList<>(Math.min(maxSequenceLength, 32));
        ids.add(clsId);
        for (String word : basicTokens(text)) {
            if (ids.size() >= maxSequenceLength - 1) break;
            addWordPieces(word, ids);
        }
        ids.add(sepId);

        int used = Math.min(ids.size(), maxSequenceLength);
        long[] inputIds = new long[maxSequenceLength];
        long[] attention = new long[maxSequenceLength];
        long[] types = new long[maxSequenceLength];
        for (int index = 0; index < used; index++) {
            inputIds[index] = ids.get(index);
            attention[index] = 1;
        }
        for (int index = used; index < maxSequenceLength; index++) inputIds[index] = padId;
        return new Tokenized(inputIds, attention, types);
    }

    private List<String> basicTokens(String text) {
        List<String> words = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        int offset = 0;
        while (offset < text.length()) {
            int codePoint = text.codePointAt(offset);
            offset += Character.charCount(codePoint);
            if (Character.isWhitespace(codePoint) || Character.isISOControl(codePoint)) {
                flush(words, current);
            } else if (isPunctuation(codePoint)) {
                flush(words, current);
                words.add(new String(Character.toChars(codePoint)));
            } else {
                current.appendCodePoint(codePoint);
            }
            if (words.size() >= maxSequenceLength * 2 && current.isEmpty()) break;
        }
        flush(words, current);
        return words;
    }

    private static void flush(List<String> words, StringBuilder current) {
        if (!current.isEmpty()) {
            words.add(current.toString());
            current.setLength(0);
        }
    }

    private static boolean isPunctuation(int codePoint) {
        if (codePoint >= 33 && codePoint <= 47 || codePoint >= 58 && codePoint <= 64
                || codePoint >= 91 && codePoint <= 96 || codePoint >= 123 && codePoint <= 126) {
            return true;
        }
        return switch (Character.getType(codePoint)) {
            case Character.CONNECTOR_PUNCTUATION, Character.DASH_PUNCTUATION,
                    Character.START_PUNCTUATION, Character.END_PUNCTUATION,
                    Character.INITIAL_QUOTE_PUNCTUATION, Character.FINAL_QUOTE_PUNCTUATION,
                    Character.OTHER_PUNCTUATION -> true;
            default -> false;
        };
    }

    private void addWordPieces(String word, List<Integer> ids) {
        if (word.codePointCount(0, word.length()) > MAX_WORD_CODE_POINTS) {
            addIfRoom(ids, unkId);
            return;
        }
        List<Integer> pieces = new ArrayList<>();
        int start = 0;
        while (start < word.length()) {
            int end = word.length();
            Integer match = null;
            int matchedEnd = start;
            while (end > start) {
                String candidate = word.substring(start, end);
                if (start > 0) candidate = "##" + candidate;
                match = vocab.get(candidate);
                if (match != null) {
                    matchedEnd = end;
                    break;
                }
                end = word.offsetByCodePoints(end, -1);
            }
            if (match == null) {
                pieces.clear();
                pieces.add(unkId);
                break;
            }
            pieces.add(match);
            start = matchedEnd;
        }
        for (Integer piece : pieces) {
            if (!addIfRoom(ids, piece)) return;
        }
    }

    private boolean addIfRoom(List<Integer> ids, int id) {
        if (ids.size() >= maxSequenceLength - 1) return false;
        ids.add(id);
        return true;
    }

    private int required(String token) {
        Integer id = vocab.get(token);
        if (id == null) throw new IllegalArgumentException("WordPiece vocabulary is missing " + token);
        return id;
    }
}
