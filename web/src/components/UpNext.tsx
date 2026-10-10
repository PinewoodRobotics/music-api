import {
  ListEnd,
  ListMinus,
  ListPlus,
  MoreHorizontal,
  Play,
  Radio,
  Trash2,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type HTMLAttributes,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { api, type Person, type QueueEntry, type Track } from "../lib/api";
import { byline, formatTime } from "../lib/format";
import { usePlayer } from "../state/player";
import { useToast } from "../state/toast";
import { Artwork } from "./Artwork";
import { Avatar } from "./Avatar";
import { Equalizer } from "./Equalizer";
import { RowsSkeleton } from "./Skeleton";
import { pointRect, type AnchorRect } from "./Popover";
import { TrackMenu, useTrackActions } from "./TrackMenu";
import { useSelection } from "../lib/selection";
import { PlaylistPicker } from "./library/PlaylistTools";
import { SelectionBar } from "./SelectionBar";

type RowProps = {
  track: Track;
  current?: boolean;
  playing?: boolean;
  pending?: boolean;
  addedBy?: Person | null;
  onMenu: (e: MouseEvent, fromButton?: boolean) => void;
  immersive?: boolean;
  selection?: { props: HTMLAttributes<HTMLDivElement>; selected: boolean };
};

function Row({
  track,
  current,
  playing,
  pending,
  addedBy,
  onMenu,
  immersive,
  selection,
}: RowProps) {
  return (
    <div
      tabIndex={selection ? 0 : undefined}
      onContextMenu={selection ? undefined : onMenu}
      {...selection?.props}
      title={selection ? "Double-click to play" : undefined}
      className={`group flex min-h-14 items-center gap-3 rounded-md px-2 py-1.5 outline-none ${
        selection?.selected
          ? "bg-white/[0.16]"
          : "hover:bg-white/[0.06] focus-visible:bg-white/[0.08]"
      } ${selection ? "cursor-pointer active:bg-white/[0.08]" : ""} ${pending ? "opacity-60" : ""}`}
    >
      <div className="relative shrink-0">
        <Artwork
          src={track.artwork}
          className={
            immersive
              ? "size-12 rounded-md md:size-14"
              : "size-11 rounded-[4px]"
          }
        />
        {pending && (
          <span className="absolute inset-0 grid place-items-center rounded-[4px] bg-black/50">
            <span className="size-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
          </span>
        )}
        {current && (
          <span className="absolute inset-0 grid place-items-center rounded-[4px] bg-black/50">
            <Equalizer playing={playing} />
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div
          className={`truncate ${immersive ? "text-base md:text-lg" : "text-sm"} ${current ? "text-accent" : "text-fg"}`}
        >
          {track.name}
        </div>
        <div
          className={`truncate text-white/60 ${immersive ? "text-sm md:text-base" : "text-[13px]"}`}
        >
          {byline(track)}
        </div>
        {addedBy && (
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-white/45">
            <Avatar person={addedBy} className="size-3.5 text-[8px]" />
            <span className="truncate">{addedBy.name}</span>
          </div>
        )}
      </div>
      <span className="shrink-0 text-xs text-white/50 tabular">
        {formatTime(track.duration_ms)}
      </span>
      <button
        type="button"
        aria-label={`More options for ${track.name}`}
        onClick={(e) => {
          e.stopPropagation();
          onMenu(e, true);
        }}
        onDoubleClick={(e) => e.stopPropagation()}
        className={`-mr-1 grid size-8 shrink-0 place-items-center rounded-full text-white/60 hover:text-white active:bg-white/10 [@media(hover:none)]:visible [@media(hover:none)]:size-11 ${
          selection?.selected ? "" : "md:invisible md:group-hover:visible"
        }`}
      >
        <MoreHorizontal className="size-5" />
      </button>
    </div>
  );
}

const SWIPE_REVEAL = 88;

function SwipeToRemove({
  onRemove,
  children,
}: {
  onRemove: () => void;
  children: ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  const drag = useRef<{
    x: number;
    y: number;
    base: number;
    horizontal: boolean | null;
  } | null>(null);
  const open = offset <= -SWIPE_REVEAL / 2;

  const down = (e: PointerEvent) => {
    if (e.pointerType === "mouse") return;
    drag.current = {
      x: e.clientX,
      y: e.clientY,
      base: offset,
      horizontal: null,
    };
  };
  const move = (e: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (d.horizontal === null) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      d.horizontal = Math.abs(dx) > Math.abs(dy);
    }
    if (!d.horizontal) return;
    setOffset(Math.max(-SWIPE_REVEAL * 1.6, Math.min(0, d.base + dx)));
  };
  const up = () => {
    const d = drag.current;
    drag.current = null;
    if (!d?.horizontal) return;
    if (offset < -SWIPE_REVEAL * 1.4) return onRemove();
    setOffset(offset < -SWIPE_REVEAL / 2 ? -SWIPE_REVEAL : 0);
  };

  return (
    <div
      className="relative touch-pan-y overflow-hidden rounded-md"
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onClickCapture={(e) => {
        if (!open || (e.target as Element).closest("[data-swipe-action]"))
          return;
        e.stopPropagation();
        e.preventDefault();
        setOffset(0);
      }}
    >
      {offset < 0 && (
        <button
          type="button"
          data-swipe-action
          aria-label="Remove from queue"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="absolute inset-y-0 right-0 flex items-center justify-center bg-danger px-5 text-sm font-semibold text-black"
          style={{ width: Math.max(SWIPE_REVEAL, -offset) }}
        >
          Remove
        </button>
      )}
      <div
        className="relative bg-inherit"
        style={{
          transform: offset ? `translateX(${offset}px)` : undefined,
          transition: drag.current ? "none" : "transform 220ms ease",
        }}
      >
        {children}
      </div>
    </div>
  );
}

const FADE_PX = 56;
const edgeFade = (top: boolean) =>
  `linear-gradient(to bottom, transparent 0, black ${top ? FADE_PX : 0}px, black calc(100% - ${FADE_PX}px), transparent 100%)`;

function groupTitle(
  entry: QueueEntry,
  contextName: string | undefined,
  immersive: boolean,
) {
  if (entry.source === "queue") return "Next in queue";
  if (entry.source === "autoplay") return "Autoplay";
  if (immersive) return "Playing Next";
  return contextName ? `Next from ${contextName}` : "Next up";
}

function GroupHeading({
  title,
  contextName,
  immersive,
}: {
  title: string;
  contextName?: string;
  immersive: boolean;
}) {
  if (!immersive)
    return (
      <h3 className="truncate px-2 pb-2 text-sm font-semibold text-white/90">
        {title}
      </h3>
    );
  return (
    <div className="px-2 pb-2">
      <h3 className="flex items-center gap-2 text-[17px] font-bold text-white">
        {title === "Autoplay" && <Radio className="size-4" aria-hidden />}
        {title}
      </h3>
      {title === "Playing Next" && contextName && (
        <p className="truncate text-[13px] text-white/65">From {contextName}</p>
      )}
    </div>
  );
}

export function UpNext({ immersive = false }: { immersive?: boolean }) {
  const { status, queue, isPlaying, refreshQueue, replaceQueue } = usePlayer();
  const toast = useToast();
  useEffect(refreshQueue, [refreshQueue]);
  const [jumping, setJumping] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const [menu, setMenu] = useState<{
    tracks: Track[];
    anchor: AnchorRect;
    align: "start" | "end";
    indices?: number[];
  } | null>(null);
  const [picker, setPicker] = useState<AnchorRect | null>(null);
  const upcoming = useMemo(
    () =>
      (queue?.upcoming ?? []).filter(
        (e): e is QueueEntry & { item: Track } => !!e.item,
      ),
    [queue],
  );
  const keys = useMemo(
    () => upcoming.map((e, i) => e.uid ?? `${e.item.uri}#${i}`),
    [upcoming],
  );
  const sel = useSelection(keys);
  const { queue: addToQueue, addTo } = useTrackActions();

  const groups: {
    title: string;
    entries: { entry: (typeof upcoming)[number]; index: number }[];
  }[] = [];
  upcoming.forEach((entry, index) => {
    const title = groupTitle(entry, status?.context?.name, immersive);
    const last = groups[groups.length - 1];
    if (last?.title === title) last.entries.push({ entry, index });
    else groups.push({ title, entries: [{ entry, index }] });
  });

  const jump = (index: number) => {
    const entry = upcoming[index];
    if (!entry || jumping) return;
    setJumping(keys[index]);
    sel.clear();
    api
      .jumpTo({ uid: entry.uid, index })
      .catch(() => {})
      .finally(() => {
        setJumping(null);
        refreshQueue();
      });
  };

  const remove = async (indices: number[]) => {
    if (!queue || !indices.length) return;
    const removed = indices.map((i) => upcoming[i]).filter(Boolean);
    const gone = new Set<QueueEntry>(removed);
    const uids = removed.map((e) => e.uid).filter((u): u is string => !!u);
    const before = queue;
    replaceQueue({
      ...queue,
      upcoming: queue.upcoming.filter((e) => !gone.has(e)),
    });
    sel.clear();
    try {
      const next =
        uids.length === removed.length
          ? await api.removeFromQueue({ uids })
          : await api.removeFromQueue({ index: indices[0] });
      if (next?.upcoming) replaceQueue(next);
      const label =
        removed.length === 1
          ? `Removed ${removed[0].item.name} from the queue`
          : `Removed ${removed.length} songs from the queue`;
      toast.show(label, {
        label: "Undo",
        run: () => {
          api
            .addToQueue(removed.map((e) => e.item.uri))
            .then(refreshQueue)
            .catch(toast.error);
        },
      });
    } catch (err) {
      replaceQueue(before);
      toast.error(err);
      refreshQueue();
    }
  };

  const anchorOf = (e: MouseEvent, fromButton: boolean) =>
    fromButton
      ? (e.currentTarget as HTMLElement).getBoundingClientRect()
      : pointRect(e.clientX, e.clientY);
  const openQueueMenu = (
    indices: number[],
    e: MouseEvent,
    fromButton: boolean,
  ) => {
    e.preventDefault();
    setMenu({
      tracks: indices.map((i) => upcoming[i].item),
      anchor: anchorOf(e, fromButton),
      align: fromButton ? "end" : "start",
      indices,
    });
  };
  const selectedUris = sel.indices
    .map((i) => upcoming[i]?.item.uri)
    .filter((u): u is string => !!u);

  return (
    <div
      onScroll={
        immersive
          ? (e) => setScrolled(e.currentTarget.scrollTop > 4)
          : undefined
      }
      style={
        immersive
          ? {
              maskImage: edgeFade(scrolled),
              WebkitMaskImage: edgeFade(scrolled),
            }
          : undefined
      }
      className={`scroll-thin h-full select-none overflow-y-auto overscroll-contain ${immersive ? "px-0 pb-20" : "px-3 pb-6"}`}
      {...sel.rootProps({
        primary: (ix) => jump(ix[0]),
        remove: (ix) => void remove(ix),
      })}
    >
      {status?.track && !immersive && (
        <section className="mb-4">
          <h3 className="px-2 pb-2 pt-1 text-sm font-semibold text-white/90">
            Now playing
          </h3>
          <Row
            track={status.track}
            current
            playing={isPlaying}
            onMenu={(e, fromButton = false) => {
              e.preventDefault();
              setMenu({
                tracks: [status.track!],
                anchor: anchorOf(e, fromButton),
                align: fromButton ? "end" : "start",
              });
            }}
          />
        </section>
      )}
      {groups.map((g, i) => (
        <section key={i} className="mb-4">
          <GroupHeading
            title={g.title}
            contextName={status?.context?.name}
            immersive={immersive}
          />
          {g.entries.map(({ entry, index }) => (
            <SwipeToRemove
              key={keys[index]}
              onRemove={() => void remove([index])}
            >
              <Row
                track={entry.item}
                addedBy={entry.added_by}
                immersive={immersive}
                pending={jumping === keys[index]}
                selection={{
                  props: sel.rowProps(index, {
                    primary: () => jump(index),
                    openMenu: (e, ix) => openQueueMenu(ix, e, false),
                  }),
                  selected: sel.isSelected(index),
                }}
                onMenu={(e) =>
                  openQueueMenu(sel.ensureSelected(index), e, true)
                }
              />
            </SwipeToRemove>
          ))}
        </section>
      ))}
      {!queue && <RowsSkeleton count={6} />}
      {queue && !status?.track && !upcoming.length && (
        <p className="px-2 py-8 text-center text-sm text-white/55">
          Nothing queued.
        </p>
      )}
      {status?.track && !upcoming.length && queue && (
        <p className="px-2 py-4 text-sm text-white/55">
          Nothing else is queued. Add songs from any track menu.
        </p>
      )}
      {menu && (
        <TrackMenu
          tracks={menu.tracks}
          anchor={menu.anchor}
          align={menu.align}
          onClose={() => setMenu(null)}
          extraActions={
            menu.indices
              ? [
                  {
                    label: "Play",
                    icon: <Play />,
                    run: () => jump(menu.indices![0]),
                  },
                  {
                    label:
                      menu.indices.length > 1
                        ? `Remove ${menu.indices.length} songs from queue`
                        : "Remove from queue",
                    icon: <ListMinus />,
                    run: () => void remove(menu.indices!),
                  },
                ]
              : []
          }
        />
      )}
      {sel.touchMode && (
        <SelectionBar
          count={selectedUris.length}
          noun="song"
          onDone={sel.exitTouchMode}
          actions={[
            {
              label: "Play",
              icon: <Play />,
              onClick: () => jump(sel.indices[0]),
            },
            {
              label: "Add to queue",
              icon: <ListEnd />,
              onClick: () => void addToQueue(selectedUris),
            },
            {
              label: "Add to playlist",
              icon: <ListPlus />,
              onClick: (e) =>
                setPicker(e.currentTarget.getBoundingClientRect()),
            },
            {
              label: "Remove from queue",
              icon: <Trash2 />,
              danger: true,
              onClick: () => void remove(sel.indices),
            },
          ]}
        />
      )}
      {picker && (
        <PlaylistPicker
          anchor={picker}
          onPick={(p) => void addTo(p, selectedUris)}
          onClose={() => setPicker(null)}
        />
      )}
    </div>
  );
}
