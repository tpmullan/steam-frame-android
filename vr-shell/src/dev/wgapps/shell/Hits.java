package dev.wgapps.shell;

import java.util.ArrayList;
import java.util.List;

/** Rectangles of what the shell draws, and what a pointer at (x, y) is over. No Android needed. */
public final class Hits {
    private static final class Area {
        final int left, top, right, bottom;
        final String key;

        Area(int left, int top, int right, int bottom, String key) {
            this.left = left;
            this.top = top;
            this.right = right;
            this.bottom = bottom;
            this.key = key;
        }
    }

    private final List<Area> areas = new ArrayList<>();

    public synchronized void clear() {
        areas.clear();
    }

    public synchronized void add(int left, int top, int right, int bottom, String key) {
        areas.add(new Area(left, top, right, bottom, key));
    }

    /** The key of the last area drawn over (x, y) (later ones are on top), or null. */
    public synchronized String at(int x, int y) {
        for (int i = areas.size() - 1; i >= 0; i--) {
            Area a = areas.get(i);
            if (x >= a.left && x < a.right && y >= a.top && y < a.bottom) return a.key;
        }
        return null;
    }
}
