"""Arc summariser — generates rolling summaries for narrative arcs.

Called periodically by the narrative engine to keep arc summaries fresh.
Each summary captures the current state and evolution of the storyline.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db import AsyncSessionLocal

logger = logging.getLogger("orthanc.arc_summariser")


class ArcSummariser:
    """Generates and maintains rolling LLM summaries for narrative arcs."""

    async def summarise_arcs(self) -> int:
        """Main entry point — summarise all active arcs that need updates.

        Returns:
            Number of arcs successfully summarised.
        """
        try:
            from app.models.narrative import NarrativeArc, NarrativeArcSummary
        except ImportError as exc:
            logger.warning("Arc summariser: models not available, skipping: %s", exc)
            return 0

        try:
            from app.services.model_router import model_router, ModelRouter
        except ImportError as exc:
            logger.warning("Arc summariser: model_router not available, skipping: %s", exc)
            return 0

        count = 0

        try:
            async with AsyncSessionLocal() as session:
                # Fetch all active arcs
                result = await session.execute(
                    select(NarrativeArc).where(NarrativeArc.status == "active")
                )
                arcs = result.scalars().all()

            if not arcs:
                return 0

            logger.info("Arc summariser: checking %d active arcs", len(arcs))

            for arc in arcs:
                needs_update = False

                try:
                    async with AsyncSessionLocal() as session:
                        # Get latest summary for this arc
                        latest_result = await session.execute(
                            select(NarrativeArcSummary)
                            .where(NarrativeArcSummary.arc_id == arc.id)
                            .order_by(NarrativeArcSummary.generated_at.desc())
                            .limit(1)
                        )
                        latest_summary = latest_result.scalar_one_or_none()

                    if latest_summary is None:
                        needs_update = True
                    elif arc.last_updated and arc.last_updated > latest_summary.generated_at:
                        needs_update = True

                except Exception as exc:
                    logger.warning(
                        "Arc summariser: error checking arc %s status: %s", arc.id, exc
                    )
                    continue

                if needs_update:
                    success = await self._summarise_single_arc(arc)
                    if success:
                        count += 1

        except Exception as exc:
            logger.error("Arc summariser: unexpected error in summarise_arcs: %s", exc)

        return count

    async def _summarise_single_arc(self, arc) -> bool:
        """Summarise a single arc using the LLM.

        Args:
            arc: NarrativeArc instance to summarise.

        Returns:
            True on success, False on failure.
        """
        try:
            from app.models.narrative import Narrative, NarrativeArc, NarrativeArcSummary
        except ImportError as exc:
            logger.warning("Arc summariser: models not importable: %s", exc)
            return False

        try:
            from app.services.model_router import model_router, ModelRouter
        except ImportError as exc:
            logger.warning("Arc summariser: model_router not importable: %s", exc)
            return False

        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=14)

            async with AsyncSessionLocal() as session:
                # Fetch child narratives — active + stale from last 14 days
                result = await session.execute(
                    select(Narrative)
                    .where(
                        Narrative.arc_id == arc.id,
                        Narrative.first_seen >= cutoff,
                    )
                    .order_by(Narrative.first_seen.asc())
                )
                all_narratives = result.scalars().all()

            if len(all_narratives) < 2:
                logger.debug(
                    "Arc summariser: arc %s has fewer than 2 narratives (%d), skipping",
                    arc.id,
                    len(all_narratives),
                )
                return False

            # Limit to 10 most significant for the prompt (by post_count DESC)
            prompt_narratives = sorted(
                all_narratives, key=lambda n: (n.post_count or 0), reverse=True
            )[:10]
            # Re-sort chronologically for the prompt
            prompt_narratives.sort(key=lambda n: n.first_seen or datetime.min.replace(tzinfo=timezone.utc))

            # Fetch previous summary
            async with AsyncSessionLocal() as session:
                prev_result = await session.execute(
                    select(NarrativeArcSummary)
                    .where(NarrativeArcSummary.arc_id == arc.id)
                    .order_by(NarrativeArcSummary.generated_at.desc())
                    .limit(1)
                )
                prev_summary_obj = prev_result.scalar_one_or_none()

            previous_summary = prev_summary_obj.summary if prev_summary_obj else None

            # Build narrative timeline text
            timeline_lines = []
            for n in prompt_narratives:
                first_seen_date = (
                    n.first_seen.strftime("%Y-%m-%d")
                    if n.first_seen
                    else "unknown"
                )
                post_count = n.post_count or 0
                confirmation_status = n.confirmation_status or "unconfirmed"
                canonical_claim = n.canonical_claim or "No claim extracted"
                title = n.title or "Untitled"
                timeline_lines.append(
                    f"- [{first_seen_date}] {title} ({post_count} posts, {confirmation_status}): {canonical_claim}"
                )

            timeline_text = "\n".join(timeline_lines)
            prev_text = previous_summary or "None — this is the first summary for this storyline."

            system_prompt = (
                "You are an OSINT intelligence analyst maintaining a running summary of an evolving storyline.\n"
                "Write an updated 4-6 sentence summary of this storyline's current state and evolution.\n"
                "Focus on: what started it, key escalations or shifts, current status, and trajectory.\n"
                "Output ONLY the summary text — no JSON, no headers, no explanation."
            )

            user_prompt = (
                f"STORYLINE: {arc.title}\n\n"
                f"PREVIOUS SUMMARY: {prev_text}\n\n"
                f"NARRATIVE TIMELINE (chronological):\n{timeline_text}\n\n"
                f"Write the updated summary:"
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            # Call LLM with 45s timeout
            response = await asyncio.wait_for(
                model_router.chat(ModelRouter.TASK_ARC_SUMMARY, messages),
                timeout=45.0,
            )

            summary_text = response.get("content", "").strip()
            model_name = response.get("model", "")

            if not summary_text:
                logger.warning("Arc summariser: empty summary response for arc %s", arc.id)
                return False

            now = datetime.now(timezone.utc)

            # Store new summary and update arc
            async with AsyncSessionLocal() as session:
                new_summary = NarrativeArcSummary(
                    arc_id=arc.id,
                    summary=summary_text,
                    post_count=arc.total_post_count or 0,
                    narrative_count=len(all_narratives),
                    generated_at=now,
                    model=model_name,
                )
                session.add(new_summary)

                # Update arc.summary
                arc_obj = await session.get(NarrativeArc, arc.id)
                if arc_obj:
                    arc_obj.summary = summary_text
                    arc_obj.last_updated = now

                await session.commit()

            logger.info(
                "Arc summariser: summarised arc %s (%d narratives, model=%s)",
                arc.id,
                len(all_narratives),
                model_name,
            )

            # Optionally refine the arc title
            await self._update_arc_title(arc, all_narratives)

            return True

        except asyncio.TimeoutError:
            logger.warning("Arc summariser: LLM timeout for arc %s (45s exceeded)", arc.id)
            return False
        except Exception as exc:
            logger.warning("Arc summariser: failed to summarise arc %s: %s", arc.id, exc)
            return False

    async def _update_arc_title(self, arc, narratives: list) -> None:
        """Optionally refine the arc title if it has grown beyond a single-event framing.

        Only triggers when narrative_count >= 5 and the current title exactly matches
        one of the child narrative titles (heuristic for stale single-event titles).
        """
        try:
            from app.models.narrative import NarrativeArc
        except ImportError:
            return

        try:
            from app.services.model_router import model_router, ModelRouter
        except ImportError:
            return

        try:
            if (arc.narrative_count or len(narratives)) < 5:
                return

            child_titles = [n.title for n in narratives if n.title]
            if arc.title not in child_titles:
                return  # Title has already been evolved beyond any single child

            # Limit to 10 titles for prompt
            prompt_titles = child_titles[:10]
            titles_text = "\n".join(f"- {t}" for t in prompt_titles)

            messages = [
                {
                    "role": "user",
                    "content": (
                        "Given these narrative titles from an evolving storyline, generate a concise "
                        "overarching title (max 8 words) that captures the full scope.\n\n"
                        f"Titles:\n{titles_text}\n\n"
                        "Output ONLY the title text."
                    ),
                }
            ]

            response = await asyncio.wait_for(
                model_router.chat(ModelRouter.TASK_ARC_DISCOVERY, messages),
                timeout=45.0,
            )

            new_title = response.get("content", "").strip()
            if not new_title or new_title == arc.title:
                return

            async with AsyncSessionLocal() as session:
                arc_obj = await session.get(NarrativeArc, arc.id)
                if arc_obj:
                    arc_obj.title = new_title
                    await session.commit()

            logger.info(
                "Arc summariser: updated title for arc %s: %r → %r",
                arc.id,
                arc.title,
                new_title,
            )

        except asyncio.TimeoutError:
            logger.warning("Arc summariser: title update timeout for arc %s", arc.id)
        except Exception as exc:
            logger.warning("Arc summariser: title update failed for arc %s: %s", arc.id, exc)


arc_summariser = ArcSummariser()
