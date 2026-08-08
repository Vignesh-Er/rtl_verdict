module miter (
	input clk,
	input rst_n,
	input tx_start,
	input [7:0] tx_data
);
	wire ref_tx, ref_tx_busy, uut_tx, uut_tx_busy;

	uart ref_i (.clk(clk), .rst_n(rst_n), .tx_start(tx_start), .tx_data(tx_data), .tx(ref_tx), .tx_busy(ref_tx_busy));
	uart_mutant_shallow uut_i (.clk(clk), .rst_n(rst_n), .tx_start(tx_start), .tx_data(tx_data), .tx(uut_tx), .tx_busy(uut_tx_busy));

	initial assume(!rst_n);

	always @* begin
		if (rst_n) begin
			assert (ref_tx == uut_tx);
			assert (ref_tx_busy == uut_tx_busy);
		end
	end
endmodule
