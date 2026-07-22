"""Functions for merging duplicate/similar names within pokedata entries."""

from collections import defaultdict
from difflib import SequenceMatcher

from total_cp_parser import TotalCPEntry


def find_similar_names(entries: list[TotalCPEntry], similarity_threshold: float = 0.75) -> list[tuple[str, str, float]]:
    """Find pairs of similar normalized names.
    
    Returns list of (name1, name2, similarity_score) tuples.
    """
    # Group entries by normalized name
    name_groups: dict[str, list[TotalCPEntry]] = defaultdict(list)
    for entry in entries:
        norm_name = entry.normalized_name
        name_groups[norm_name].append(entry)

    # Find similar names
    similar_pairs = []
    names_list = sorted(name_groups.keys())

    for i, name1 in enumerate(names_list):
        for name2 in names_list[i+1:]:
            # Check similarity
            similarity = SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
            if similarity >= similarity_threshold:
                similar_pairs.append((name1, name2, similarity))

    return similar_pairs


def merge_duplicate_entries(entries: list[TotalCPEntry], merge_mappings: dict[str, str]) -> list[TotalCPEntry]:
    """Merge entries based on name mappings.
    
    Args:
        entries: List of entries to merge
        merge_mappings: Dict mapping source normalized name -> target normalized name
    
    Returns:
        Merged list of entries
    """
    # Group entries by their target name (after mapping)
    merged_map: dict[str, TotalCPEntry] = {}

    for entry in entries:
        norm_name = entry.normalized_name
        # Apply merge mapping if exists
        target_name = merge_mappings.get(norm_name, norm_name)

        if target_name not in merged_map:
            # Create new entry with target name
            merged_entry = TotalCPEntry(
                rank=entry.rank,
                raw_name=entry.raw_name,  # Keep original raw name
                country=entry.country,
                current_points=entry.current_points,
                date_points=entry.date_points.copy(),
            )
            merged_map[target_name] = merged_entry
        else:
            # Merge into existing entry
            existing = merged_map[target_name]
            # Keep the entry with higher current_points
            if entry.current_points > existing.current_points:
                existing.current_points = entry.current_points
                existing.rank = entry.rank
                # Merge date_points (keep unique dates, prefer newer data)
                existing_dates = {dp[0]: dp for dp in existing.date_points}
                for date, total, diff in entry.date_points:
                    if date not in existing_dates or total > existing_dates[date][1]:
                        existing_dates[date] = (date, total, diff)
                existing.date_points = sorted(existing_dates.values(), key=lambda x: x[0], reverse=True)

    return list(merged_map.values())

