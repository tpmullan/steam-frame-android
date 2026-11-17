import dev.wgapps.shell.Hits;

/** Run with `java -ea`: tools/build-shell.sh does. */
public class HitsTest {
    static void check(boolean ok, String what) {
        if (!ok) throw new AssertionError(what);
    }

    public static void main(String[] args) {
        Hits hits = new Hits();
        check(hits.at(5, 5) == null, "nothing drawn, nothing hit");
        hits.add(0, 0, 100, 100, "tile");
        hits.add(40, 40, 60, 60, "badge"); // drawn later, so on top
        check("tile".equals(hits.at(10, 10)), "inside the tile");
        check("badge".equals(hits.at(50, 50)), "the later area is on top");
        check(hits.at(100, 50) == null && hits.at(50, 100) == null, "right and bottom edges are outside");
        check("tile".equals(hits.at(0, 0)), "left and top edges are inside");
        check(hits.at(-1, -1) == null, "the pointer off the panel (-1, -1) hits nothing");
        hits.clear();
        check(hits.at(10, 10) == null, "cleared");
        System.out.println("HitsTest ok");
    }
}
