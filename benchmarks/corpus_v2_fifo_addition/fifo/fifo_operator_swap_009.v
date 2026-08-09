module fifo #(
    parameter DEPTH = 8,
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             wr_en,
    input  wire [WIDTH-1:0] wr_data,
    input  wire             rd_en,
    output reg  [WIDTH-1:0] rd_data,
    output wire             full,
    output wire             empty
);
    localparam AW = 3; // log2(DEPTH)

    reg [WIDTH-1:0] mem [0:DEPTH-1];
    reg [AW:0] wr_ptr;
    reg [AW:0] rd_ptr;

    assign full  = (wr_ptr[AW] != rd_ptr[AW]) && (wr_ptr[AW-1:0] == rd_ptr[AW-1:0]);
    assign empty = (wr_ptr != rd_ptr);

    always @(posedge clk) begin
        if (!rst_n) begin
            wr_ptr  <= 0;
            rd_ptr  <= 0;
            rd_data <= 0;
        end else begin
            if (wr_en && !full) begin
                mem[wr_ptr[AW-1:0]] <= wr_data;
                wr_ptr <= wr_ptr + 1'b1;
            end
            if (rd_en && !empty) begin
                rd_data <= mem[rd_ptr[AW-1:0]];
                rd_ptr <= rd_ptr + 1'b1;
            end
        end
    end
endmodule
