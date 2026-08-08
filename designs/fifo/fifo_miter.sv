module miter (
	input clk,
	input rst_n,
	input wr_en,
	input [7:0] wr_data,
	input rd_en
);
	wire [7:0] ref_rd_data, uut_rd_data;
	wire ref_full, ref_empty, uut_full, uut_empty;

	fifo ref_i (.clk(clk), .rst_n(rst_n), .wr_en(wr_en), .wr_data(wr_data), .rd_en(rd_en),
	            .rd_data(ref_rd_data), .full(ref_full), .empty(ref_empty));
	fifo uut_i (.clk(clk), .rst_n(rst_n), .wr_en(wr_en), .wr_data(wr_data), .rd_en(rd_en),
	            .rd_data(uut_rd_data), .full(uut_full), .empty(uut_empty));

	initial assume(!rst_n);

	always @* begin
		if (rst_n) begin
			assert (ref_full == uut_full);
			assert (ref_empty == uut_empty);
			assert (ref_rd_data == uut_rd_data);
		end
	end
endmodule
