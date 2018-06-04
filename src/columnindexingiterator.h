#ifndef COLUMN_INDEXING_ITERATOR_H
#define COLUMN_INDEXING_ITERATOR_H

#include "generalizedgraycode.h"

class ColumnIndexingScheme;

class ColumnIndexingIterator {
private:
	const ColumnIndexingScheme* parent;
	GeneralizedGrayCodes* graycodes;
	unsigned int index;
	unsigned int forward_projection;
	unsigned int number_of_partitions;

public:
	ColumnIndexingIterator(const ColumnIndexingScheme* parent, unsigned int number_of_partitions);
	virtual ~ColumnIndexingIterator();

	bool has_next();

	/** Move to next index (i.e. DP table row).
	  *
	  *  @param bit_changed If not null, and only one bit in the
	  *  partitioning (as retrieved by get_partition) is changed by this
	  *  call to advance, then the index of this bit is written to the
	  *  referenced variable; if not, -1 is written.
	  */
	void advance(int* position_changed, int* partition_changed);

	/** Index of the projection of the current read set onto the intersection between current and next read set. */
	unsigned int get_forward_projection();

	/** Index of the projection of the current read set onto the intersection between previous and the current read set. */
	unsigned int get_backward_projection();

	/** Row index in the DP table (within the current column). */
	unsigned int get_index();

	/** Bit-wise representation of the partitioning corresponding to the current index. */
	unsigned int get_partition();

	/** get index's backward projection (given index i), so that we don't have to iterate up to it, just to get it */
	unsigned int index_backward_projection(unsigned int i);

	/** get index's forward projection */
	unsigned int index_forward_projection(unsigned int i);

	/** update given index by switching read_to_switch to value new_partition **/
	unsigned int switch_read(unsigned int old_index, unsigned int read_to_switch, unsigned int new_partition, unsigned int used_bits);
};

#endif
