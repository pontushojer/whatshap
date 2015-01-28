#!/usr/bin/env python3
"""
Read a VCF and a BAM file and phase the variants. The phased VCF is written to
standard output.
"""
"""
 0: ref allele
 1: alt allele
 -: unphasable: no coverage of read that covers at least 2 SNPs
 X: unphasable: there is coverage, but still not phasable (tie)

TODO
* Perhaps simplify slice_reads() such that it only creates and returns one slice
* it would be cleaner to not open the input VCF twice
* convert parse_vcf to a class so that we can access VCF header info before
  starting to iterate (sample names)
"""
import os
import logging
import sys
import random
import gzip
import time
import itertools
import platform
from collections import defaultdict
try:
	from contextlib import ExitStack, closing
except ImportError:
	from contextlib2 import ExitStack, closing  # PY32
from ..vcf import parse_vcf, PhasedVcfWriter
from .. import __version__
from ..args import HelpfulArgumentParser as ArgumentParser
from ..core import Read, ReadSet, DPTable, IndexSet
from ..graph import ComponentFinder
from ..bam import MultiBamReader, SampleBamReader

__author__ = "Murray Patterson, Alexander Schönhuth, Tobias Marschall, Marcel Martin"

logger = logging.getLogger(__name__)


def covered_variants(variants, start, bam_read):
	"""
	Find the variants that are covered by the given bam_read and return a
	core.Read instance that represents those variants. The instance may be
	empty.

	start -- index of the first variant (in the variants list) to check
	"""
	core_read = Read(bam_read.qname, bam_read.mapq)
	j = start  # index into variants list
	ref_pos = bam_read.pos  # position relative to reference
	query_pos = 0  # position relative to read
	errors = 0
	for cigar_op, length in bam_read.cigar:
		# The mapping of CIGAR operators to numbers is:
		# MIDNSHPX= => 012345678
		if cigar_op in (0, 7, 8):  # we are in a matching region
			# Skip variants that come before this region
			while j < len(variants) and variants[j].position < ref_pos:
				j += 1

			# Iterate over all variants that are in this region
			while j < len(variants) and variants[j].position < ref_pos + length:
				offset = variants[j].position - ref_pos
				base = bam_read.seq[query_pos + offset]
				allele = None
				if base == variants[j].reference_allele:
					allele = 0
				elif base == variants[j].alternative_allele:
					allele = 1
				else:
					# TODO this variable is unused
					errors += 1
				if allele is not None:
					# TODO this assertion should be removed
					assert variants[j].position not in core_read
					# Do not use bam_read.qual here as it is extremely slow.
					# If we ever decide to be compatible with older pysam
					# versions, cache bam_read.qual somewhere - do not
					# access it within this loop (3x slower otherwise).
					core_read.add_variant(variants[j].position, base, allele, bam_read.query_qualities[query_pos + offset])
				j += 1
			query_pos += length
			ref_pos += length
		elif cigar_op == 1:  # an insertion
			query_pos += length
		elif cigar_op == 2 or cigar_op == 3:  # a deletion or a reference skip
			ref_pos += length
		elif cigar_op == 4:  # soft clipping
			query_pos += length
		elif cigar_op == 5 or cigar_op == 6:  # hard clipping or padding
			pass
		else:
			logger.error("Unsupported CIGAR operation: %d", cigar_op)
			sys.exit(1)
	return core_read


class BamReader:
	"""
	Associate variants with reads.
	"""
	def __init__(self, paths, mapq_threshold=20):
		self._mapq_threshold = mapq_threshold
		if len(paths) == 1:
			self._reader = SampleBamReader(paths[0])
		else:
			self._reader = MultiBamReader(paths)

	def read(self, chromosome, variants, sample):
		"""
		chromosome -- name of chromosome to work on
		variants -- list of Variant objects (obtained from VCF with parse_vcf)
		sample -- name of sample to work on. If None, read group information is
			ignored and all reads in the file are used.

		Return a ReadSet object.
		"""
		# Map read name to a list of Read objects. The list has two entries
		# if it is a paired-end read, one entry if the read is single-end.
		reads = defaultdict(list)

		i = 0  # keep track of position in variants array (which is in order)
		for bam_read in self._reader.fetch(reference=chromosome, sample=sample):
			# TODO: handle additional alignments correctly! find out why they are sometimes overlapping/redundant
			if bam_read.flag & 2048 != 0:
				# print('Skipping additional alignment for read ', bam_read.qname)
				continue
			if bam_read.mapq < self._mapq_threshold:
				continue
			if bam_read.is_secondary:
				continue
			if bam_read.is_unmapped:
				continue
			if not bam_read.cigar:
				continue

			# Skip variants that are to the left of this read.
			while i < len(variants) and variants[i].position < bam_read.pos:
				i += 1

			core_read = covered_variants(variants, i, bam_read)
			# Only add new read if it covers at least one variant.
			if core_read:
				reads[bam_read.qname].append(core_read)

		# Prepare resulting set of reads.
		read_set = ReadSet()

		for readlist in reads.values():
			assert 0 < len(readlist) <= 2
			if len(readlist) == 1:
				read_set.add(readlist[0])
			else:
				read_set.add(self._merge_pair(*readlist))
		return read_set

	def _merge_pair(self, read1, read2):
		"""
		Merge the two ends of a paired-end read into a single core.Read. Also
		takes care of self-overlapping read pairs.

		TODO this can be simplified as soon as a variant in a read can be
		modified.
		"""
		if read2:
			result = Read(read1.name, read1.mapqs[0])
			result.add_mapq(read2.mapqs[0])
		else:
			return read1

		i1 = 0
		i2 = 0

		def add1():
			result.add_variant(read1[i1].position, read1[i1].base, read1[i1].allele, read1[i1].quality)

		def add2():
			result.add_variant(read2[i2].position, read2[i2].base, read2[i2].allele, read2[i2].quality)

		while i1 < len(read1) or i2 < len(read2):
			if i1 == len(read1):
				add2()
				i2 += 1
				continue
			if i2 == len(read2):
				add1()
				i1 += 1
				continue
			variant1 = read1[i1]
			variant2 = read2[i2]
			if variant2.position < variant1.position:
				add2()
				i2 += 1
			elif variant2.position > variant1.position:
				add1()
				i1 += 1
			else:
				# Variant on self-overlapping read pair
				assert read1[i1].position == read2[i2].position
				# If both alleles agree, merge into single variant and add up qualities
				if read1[i1].allele == read2[i2].allele:
					quality = read1[i1].quality + read2[i2].quality
					result.add_variant(read1[i1].position, read1[i1].base, read1[i1].allele, quality)
				else:
					# Otherwise, take variant with highest base quality and discard the other.
					if read1[i1].quality >= read2[i2].quality:
						add1()
					else:
						add2()
				i1 += 1
				i2 += 1
		return result

	def __enter__(self):
		return self

	def __exit__(self, *args):
		self.close()

	def close(self):
		self._reader.close()


class CoverageMonitor:
	'''TODO: This is a most simple, naive implementation. Could do this smarter.'''
	def __init__(self, length):
		self.coverage = [0] * length

	def max_coverage_in_range(self, begin, end):
		return max(self.coverage[begin:end])

	def add_read(self, begin, end):
		for i in range(begin, end):
			self.coverage[i] += 1


def slice_reads(reads, max_coverage):
	"""
	Iterate over all read in random order and greedily retain those reads whose
	addition does not lead to a local physical coverage exceeding the given threshold.
	Return a ReadSet containing the retained reads.

	max_coverage -- Slicing ensures that the (physical) coverage does not exceed max_coverage anywhere along the chromosome.
	reads -- a ReadSet
	"""
	shuffled_indices = list(range(len(reads)))
	random.shuffle(shuffled_indices)

	position_list = reads.get_positions()
	logger.info('Found %d SNP positions', len(position_list))

	# dictionary to map SNP position to its index
	position_to_index = { position: index for index, position in enumerate(position_list) }

	# List of slices, start with one empty slice ...
	slices = [IndexSet()]
	# ... and the corresponding coverages along each slice
	slice_coverages = [CoverageMonitor(len(position_list))]
	skipped_reads = 0
	accessible_positions = set()
	for index in shuffled_indices:
		read = reads[index]
		# Skip reads that cover only one SNP
		if len(read) < 2:
			skipped_reads += 1
			continue
		for variant in read:
			accessible_positions.add(variant.position)
		begin = position_to_index[read[0].position]
		end = position_to_index[read[-1].position] + 1
		slice_id = 0
		while True:
			# Does current read fit into this slice?
			if slice_coverages[slice_id].max_coverage_in_range(begin, end) < max_coverage:
				slice_coverages[slice_id].add_read(begin, end)
				slices[slice_id].add(index)
				break
			else:
				slice_id += 1
				# do we have to create a new slice?
				if slice_id == len(slices):
					slices.append(IndexSet())
					slice_coverages.append(CoverageMonitor(len(position_list)))
	logger.info('Skipped %d reads that only cover one SNP', skipped_reads)

	unphasable_snps = len(position_list) - len(accessible_positions)
	if position_list:
		logger.info('%d out of %d variant positions (%.1d%%) do not have a read '
			'connecting them to another variant and are thus unphasable',
			unphasable_snps, len(position_list),
			100. * unphasable_snps / len(position_list))

	if reads:
		logger.info('After coverage reduction: Using %d of %d (%.1f%%) reads',
			len(slices[0]), len(reads), 100. * len(slices[0]) / len(reads))

	return reads.subset(slices[0])


def find_components(superreads, reads):
	"""
	Return a dict that maps each position to the component it is in. A
	component is identified by the position of its leftmost variant.
	"""
	logger.debug('Finding connected components ...')
	assert len(superreads) == 2
	assert len(superreads[0]) == len(superreads[1])

	phased_positions = [ variant.position for variant in superreads[0] if variant.allele in [0, 1] ]  # TODO set()
	assert phased_positions == sorted(phased_positions)

	# Find connected components.
	# A component is identified by the position of its leftmost variant.
	component_finder = ComponentFinder(phased_positions)
	phased_positions = set(phased_positions)
	for read in reads:
		positions = [ variant.position for variant in read if variant.position in phased_positions ]
		for position in positions[1:]:
			component_finder.merge(positions[0], position)
	components = { position : component_finder.find(position) for position in phased_positions }
	logger.info('No. of variants considered for phasing: %d', len(superreads[0]))
	logger.info('No. of variants that were phased: %d', len(phased_positions))
	return components


def best_case_blocks(reads):
	"""
	Given a list of core reads, determine the number of phased blocks that
	would result if each variant were actually phased.

	Return the number of connected components.
	"""
	positions = set()
	for read in reads:
		for variant in read:
			positions.add(variant.position)
	component_finder = ComponentFinder(positions)
	for read in reads:
		read_positions = [ variant.position for variant in read ]
		for position in read_positions[1:]:
			component_finder.merge(read_positions[0], position)
	# A dict that maps each position to the component it is in.
	components = { component_finder.find(position) for position in positions }
	return len(components)


def ensure_pysam_version():
	from pysam import __version__ as pysam_version
	from distutils.version import LooseVersion
	if LooseVersion(pysam_version) < LooseVersion("0.8.1"):
		sys.exit("WhatsHap requires pysam >= 0.8.1")


def main():
	ensure_pysam_version()
	logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
	parser = ArgumentParser(prog='whatshap', description=__doc__)
	parser.add_argument('--version', action='version', version=__version__)
	parser.add_argument('-o', '--output', default=None,
		help='Output VCF file. If omitted, use standard output.')
	parser.add_argument('--max-coverage', '-H', metavar='MAXCOV', default=15, type=int,
		help='Reduce coverage to at most MAXCOV (default: %(default)s).')
	parser.add_argument('--mapping-quality', '--mapq', metavar='QUAL',
		default=20, type=int, help='Minimum mapping quality (default: %(default)s)')
	parser.add_argument('--seed', default=123, type=int, help='Random seed (default: %(default)s)')
	parser.add_argument('--all-het', action='store_true', default=False,
		help='Assume all positions to be heterozygous (that is, fully trust SNP calls).')
	parser.add_argument('--ignore-read-groups', default=False, action='store_true',
		help='Ignore read groups in BAM header and assume all reads come '
		'from the same sample.')
	parser.add_argument('--sample', metavar='SAMPLE', default=None,
		help='Name of a sample to phase. If not given, only the first sample '
			'in the input VCF is phased.')
	parser.add_argument('vcf', metavar='VCF', help='VCF file')
	parser.add_argument('bam', nargs='+', metavar='BAM', help='BAM file')
	args = parser.parse_args()
	random.seed(args.seed)

	start_time = time.time()
	class Statistics:
		pass
	stats = Statistics()
	stats.n_phased_blocks = 0
	stats.n_best_case_blocks = 0
	stats.n_best_case_blocks_cov = 0
	logger.info("This is WhatsHap %s running under Python %s", __version__, platform.python_version())
	with ExitStack() as stack:
		try:
			bam_reader = stack.enter_context(closing(BamReader(args.bam, mapq_threshold=args.mapping_quality)))
		except OSError as e:
			logging.error(e)
			sys.exit(1)
		if args.output is not None:
			out_file = stack.enter_context(open(args.output, 'w'))
		else:
			out_file = sys.stdout
		command_line = ' '.join(sys.argv[1:])
		vcf_writer = PhasedVcfWriter(command_line=command_line, in_path=args.vcf, out_file=out_file)
		vcf_reader = parse_vcf(args.vcf, args.sample)
		for sample, chromosome, variants in vcf_reader:
			logger.info('Working on chromosome %s', chromosome)
			logger.info('Read %d variants', len(variants))
			if args.ignore_read_groups:
				sample = None
			logger.info('Reading the BAM file ...')
			reads = bam_reader.read(chromosome, variants, sample)
			logger.info('%d reads found', len(reads))
			
			# Sort the variants stored in each read
			# TODO: Check whether this is already ensured by construction
			for read in reads:
				read.sort()
			# Sort reads in read set by position
			reads.sort()

			sliced_reads = slice_reads(reads, args.max_coverage)
			n_best_case_blocks = best_case_blocks(reads)
			n_best_case_blocks_cov = best_case_blocks(sliced_reads)
			stats.n_best_case_blocks += n_best_case_blocks
			stats.n_best_case_blocks_cov += n_best_case_blocks_cov
			logger.info('Best-case phasing would result in %d phased blocks (%d with coverage reduction)',
				n_best_case_blocks, n_best_case_blocks_cov)
			logger.info('Phasing the variants (using %d reads)...', len(sliced_reads))

			# Run the core algorithm: construct DP table ...
			dp_table = DPTable(sliced_reads, args.all_het)
			# ... and do the backtrace to get the solution
			superreads = dp_table.get_super_reads()

			components = find_components(superreads, sliced_reads)
			n_phased_blocks = len(set(components.values()))
			stats.n_phased_blocks += n_phased_blocks
			logger.info('No. of phased blocks: %d', n_phased_blocks)
			vcf_writer.write(chromosome, sample, superreads, components)
			logger.info('Chromosome %s finished', chromosome)

	logger.info('== SUMMARY ==')
	logger.info('Best-case phasing would result in %d phased blocks (%d with coverage reduction)',
				stats.n_best_case_blocks, stats.n_best_case_blocks_cov)
	logger.info('Actual number of phased blocks: %d', stats.n_phased_blocks)
	logger.info('Elapsed time: %.1fs', time.time() - start_time)